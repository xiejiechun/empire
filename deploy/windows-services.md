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

这是显式操作，仅在已配置的数据库中创建缺失的 `stock`、`finance_news`、`trade_calendar` 三张业务表，以及 `collection_state` 统一归档状态表和 `app_setting` 配置表。不会创建数据库、删除旧表、修改已有字段或搬运历史记录。旧结构的简化通过针对性 SQL 和变更记录单独处理，`init-db` 不代替该过程。

已有表结构不兼容时，保留实际结构并报错；需要按具体差异直接修改 MySQL，不能通过反复初始化覆盖已有表。

## 容量设置

2026-09-23 的一次历史快照中，本机共享 Redis 约使用 52.9 GiB / 64 GiB（82.7%）；该数值不是当前容量，也不能作为换机器后的配置依据。当前示例配置采用：

- 达到全实例内存 70% 时暂停本项目采集，降至 50% 以下后恢复。
- 本项目默认最多保留 100,000 条待归档消息，单页发布最多 512 KiB；整批股票发布还须预留完整剩余批次。
- 换机器时应根据 Redis 与其他业务的实测容量调整，但归档索引容量必须覆盖队列上限。

这些设置只控制本项目采集，不会修改 Redis 全局配置。任何暂停都保留断点和已入队数据。完整列表发布前的规范化分页保留在同一 Redis Stream，队列容量必须容纳完整批次；不能裁剪未归档数据释放容量。

采集与归档记录每项目各保留 100 条，错误每项目保留 300 条且原文样本每条最多 64 KiB，都不写 MySQL。Redis 服务或电脑重启后，待归档数据、断点、next_due、频控许可/冷却及运行记录会丢失；任务、网站频控和下载资源配置保存在 MySQL `app_setting`，不会随 Redis 重启丢失。只重启 Empire 且 Redis 仍运行时可以续跑。
