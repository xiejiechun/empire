# Windows 服务接入

应用直接连接 Windows 可运行的 Redis 兼容服务和 MySQL，或用户已有实例。不使用 Docker Desktop / WSL2，不自动安装、升级或修改数据库服务的全局配置。

## 本次接入

- MySQL：`127.0.0.1:3307`，数据库 `empire`；2026-09-23 已核验 MySQL 8.4.9。
- Redis：`127.0.0.1:6379`，逻辑库 `0`；2026-09-23 已核验 Redis 8.6.3，AOF 与自动快照关闭，内存淘汰策略为 `noeviction`。
- 连接凭据在当前用户 `%LOCALAPPDATA%\Empire\config.toml`，不放入程序目录；复制或发布 `dist/Empire` 不会携带本机密码。
- 本项目 Redis 数据使用 `empire:dev` 前缀；测试使用 `empire:test:<随机标识>`，不扫描或清理其他业务的 key。

服务数据目录独立于应用代码与 `.venv`。用户于 2026-09-23 要求减少写盘：Redis 使用内存模式，配置 `appendonly no`、`save ""`、`loglevel nothing`、`logfile /dev/null`。`dbfilename volatile-no-snapshot.rdb` 指向未生成的新文件，避免下次启动加载旧 dump；已有快照/AOF 不再加载，但没有删除共享数据备份。MySQL_Empire 使用 `skip-log-bin`、`general-log=OFF`、`slow-query-log=OFF`、`log-output=NONE`、`log-error=NUL`、空 `log-error-services`。redo/undo 保留。维护记录见 `sql/changes/2026-09-23-low-write.md`。

故障分类、RPO/RTO 当前边界、MySQL 逻辑备份和严格隔离恢复演练统一见 [故障恢复与隔离演练手册](../docs/recovery-runbook.md)。当前未登记已验证备份；Redis 内存状态不在 MySQL 备份中，服务重启后按业务规则重新采集，不能从统一状态伪造待归档数据或运行记录。

## 只读检查

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire doctor
```

连接检查验证命令可用性并报告持久化状态，AOF 关闭不再阻止启动。MySQL 插件启动还会检查所需表、字段、幂等主键与 InnoDB 引擎；不自动执行 DDL。

## 首次建表

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire init-db
```

这是新空库的显式操作，按 sql/schema.sql 创建十四张业务表（含停复牌来源日期关系表），以及 collection_state 统一归档状态表和 app_setting 配置表。不会创建数据库、删除旧表、修改已有字段或搬运历史记录。旧结构的简化通过针对性 SQL 和变更记录单独处理，`init-db` 不代替该过程。

已有表结构不兼容时，保留实际结构并报错；旧版完整业务库须走 scripts/migrate_business_schema.py 显式升级，不能通过反复初始化覆盖已有表。

## 容量设置

2026-09-23 的一次历史快照中，本机共享 Redis 约使用 52.9 GiB / 64 GiB（82.7%）；该数值不是当前容量，也不能作为换机器后的配置依据。当前示例配置采用：

- 达到全实例内存 70% 时暂停本项目采集，降至 50% 以下后恢复。
- 本项目默认最多保留 100,000 条待归档消息，单页发布最多 512 KiB；整批股票发布还须预留完整剩余批次。
- 换机器时应根据 Redis 与其他业务的实测容量调整，但归档索引容量必须覆盖队列上限。

这些设置只控制本项目采集，不会修改 Redis 全局配置。任何暂停都保留断点和已入队数据。完整列表发布前的规范化分页保留在同一 Redis Stream，队列容量必须容纳完整批次；不能裁剪未归档数据释放容量。

采集与归档记录每项目各保留 100 条，错误每项目保留 300 条且原文样本每条最多 64 KiB，都不写 MySQL。Redis 服务或电脑重启后，待归档数据、断点、next_due、频控许可/冷却及运行记录会丢失；任务、网站频控和下载资源配置保存在 MySQL `app_setting`，不会随 Redis 重启丢失。只重启 Empire 且 Redis 仍运行时可以续跑。

通达信增发送配新增 `dividend_plan`（分红送转）、`additional_issue`（增发）、`rights_issue`（配股）三张独立业务表，仍共用 `collection_state` 每项目一行状态。显式维护入口为 `scripts/migrate_business_schema.py`，应用启动不改表。生命周期、来源口径与操作见 [通达信增发送配](../docs/tdx-capital-actions.md)。

财务报表使用 `income_statement`（利润表）、`balance_statement`（资产负债表）和 `cashflow_statement`（现金流量表）。这些表属于独立财报功能，本次增发详情增量优化不修改这些表，也不执行其数据库维护。


### 同花顺财报存储

`income_statement`、`balance_statement`、`cashflow_statement` 分别保存利润、资产负债和现金流量报表，以 `(unified_code, report_date)` 为主键，当前只支持来源 report 口径。JSON payload 保存规范科目、单位和舍入精度，不保存原始响应。三项目各自使用统一 collection_state；恢复清单包括三张表。运行前显式执行 scripts/migrate_business_schema.py，应用启动不自动建表。

行业业务表：`industry` 保存最新目录，`industry_member` 保存最新成分；统一状态仍为 `collection_state`。新增结构使用 `scripts/migrate_business_schema.py` 显式维护，既有业务不删除，无历史变化记录。

开盘啦七项使用 `stock_market_day` 业务头与各项类型化事实表，按 `(kind, unified_code, trade_date)` 原子归档各项独立证券日；旧 `stock_intraday` 经显式拆分核验后删除。成功原文不保存。旧版完整库通过 `scripts/migrate_business_schema.py migrate` 显式转换，启动不建表。维护前正常关闭 Empire，待归档业务经正式链路排空，前后核对规范内容；旧表保留为恢复副本。现行清单共二十四张表；各项业务仍共用 collection_state 与 app_setting。

## 2026-10 业务结构升级

`suspension_source_date` 保存事件出现的来源日期关系；`suspension_event.source_dates_known` 表达未知与已知。固定来源业务表不再重复保存 source，证券键统一为 unified_code；新闻和项目状态仍保存 source。升级前关闭程序，用 scripts/migrate_business_schema.py 的 migrate / verify 显式转换并核对，正常启动不改表。旧单表新增脚本已退役，新空库使用 init-db。迁移失败保持停机并用同一日志 resume；恢复业务写入后不直接回滚旧副本。

现行基础表清单（另含下节八张行情事实表）：`stock`、`industry`、`industry_member`、`income_statement`、`balance_statement`、`cashflow_statement`、`dividend_plan`、`additional_issue`、`rights_issue`、`suspension_event`、`trade_calendar`、`finance_news`、`collection_state`、`app_setting`、`suspension_source_date`、`stock_market_day`。

新增证券日业务表 `stock_market_day`：七个开盘啦项目独立归档，共享类型、证券及日期主键。旧 `stock_intraday` 只作为显式迁移来源，核验转换后删除。新任务默认停用，不自动下载历史。


七项有类型行情事实表：`stock_intraday_trend`、`stock_opening_auction`、`stock_minute_volume`、`stock_intraday_trade_block`、`stock_minute_entrust`、`stock_large_order_trend`、`stock_daily_quote`、`stock_daily_quote_level`。`stock_market_day`为聚合业务头，分笔块解码受契约字节上限约束；这些表与其他业务同属正式备份/恢复范围，旧维护副本另行保留。


更名事件使用`security_name_change`有类型业务表；公司全称/股票简称由独立任务采集，新增表通过scripts/create_name_change_schema.py显式维护，启动不建表。
