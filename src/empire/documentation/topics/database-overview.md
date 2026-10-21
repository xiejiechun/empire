<!-- topic:数据库参考|数据库职责与查阅 -->
<!-- summary:按持久业务、临时队列、缓存、配置和外部目录查每张表与每类键。 -->
<!-- group:总览 -->
# 数据库职责与查阅

## 程序资源与维护

表组、固定来源、查询主键及显式维护清单随程序的 sql/business-schema.json 发布，公共服务和业务模块读取同一份登记；物理字段、索引和约束仍以 sql/schema.sql 及 sql/schema-contract.json 为准。资源缺失或损坏须修复完整程序包后重启，不会从旧目录寻找替代资源，也不会自动改表。调整业务归属后须重新检查设计卡与说明；维护清单不是全部物理表，不能据它推断其他表可删除。日常查询和采集入口不变。

## 用途与归属

MySQL 保存正式业务、每项目一条已确认状态和用户配置；Redis 保存入队、断点、执行计划、频控、摘要及有界记录。Redis 是纯内存，服务重启后不承诺恢复；MySQL 已归档查询不要求 Redis 在线。连接凭据只在程序目录 config.toml，不写入正文。

## 结构与身份

下方每张 MySQL 表、每类 Redis 物理键都有独立条目。namespace 是配置中的 redis.namespace；dataset 为业务/摘要归属；project_id 是采集项目，job_key 是来源生命周期任务身份。固定来源由数据集声明，业务证券关联用 unified_code。MySQL DATETIME 保存北京时间；Redis 内部绝对时间与版本比较不重复加八小时。

## 读写与关联

| 职责 | 正式位置 | 拥有者 |
| --- | --- | --- |
| 业务结果 | MySQL 数据表 | 统一归档器调用数据集写入，数据查询服务只读 |
| 已归档状态 | [MySQL collection_state](help:MySQL%20collection_state) | 与业务同事务提交 |
| 用户配置 | [MySQL app_setting](help:MySQL%20app_setting) | SettingsStore，运行服务加载 |
| 消息与入队断点 | [Redis ingest](help:Redis%20ingest)、[Redis checkpoint](help:Redis%20checkpoint) | 统一入队器原子提交，归档器消费 |
| 摘要与过期证明 | [Redis fingerprints](help:Redis%20fingerprints)、[Redis fingerprint-expiry](help:Redis%20fingerprint-expiry) | 统一归档器/FingerprintCache |
| 运行副本与有界记录 | [Redis collection-control](help:Redis%20collection-control)、[Redis archives](help:Redis%20archives)、[Redis errors](help:Redis%20errors) | 任务控制与共享记录服务 |
| 访问许可与冷却 | [Redis rate-site](help:Redis%20rate-site)、[Redis rate-total](help:Redis%20rate-total)、[Redis rate-proxy](help:Redis%20rate-proxy) | 共享 HTTP 服务 |
| 数据准备报告 | [Redis preparation-report](help:Redis%20preparation-report) | PreparationCache |
| 代理映射与租约 | [Redis router-mapping](help:Redis%20router-mapping)、[Redis router-directory](help:Redis%20router-directory) | 外部 RouterProxy；Empire 只读 |

## 保留与恢复

成功归档、确认相同或确认旧版本后删除对应业务消息；失败保留。记录按项目配额淘汰，不把有效消息当错误样本丢弃。应用正常重启可利用仍在线 Redis 续跑；Redis 丢失后按各来源 SQL 已确认边界重新采集。配置由 MySQL 恢复，不从 Redis 运行副本迁回。

## 维护与相关说明

维护前确认队列与业务内容，正常停止归档，按对象失效摘要；维护后验证完整集合与正式查询。数据库升级只走显式维护入口，应用启动不改表。下面是逐项索引，输入真实表名或键名可直接搜索。

### MySQL 表索引

- [MySQL stock](help:MySQL%20stock)：当前股票目录，一证券一行；同花顺主目录与新浪备用发布同一份表。
- [MySQL stock_listing](help:MySQL%20stock_listing)：同花顺首次上市与发行资料，一证券一行。
- [MySQL security_listing_event](help:MySQL%20security_listing_event)：通达信暂停、恢复、终止上市来源事件。
- [MySQL finance_news](help:MySQL%20finance_news)：新浪历史财经快讯，一来源新闻 ID 一行。
- [MySQL trade_calendar](help:MySQL%20trade_calendar)：巨潮自然日日历，交易与休市都显式保存。
- [MySQL suspension_event](help:MySQL%20suspension_event)：通达信历史停复牌完整来源记录，不裁定唯一交易约束。
- [MySQL suspension_source_date](help:MySQL%20suspension_source_date)：停复牌来源记录与实际查询日历日期的多对多关联。
- [MySQL dividend_plan](help:MySQL%20dividend_plan)：通达信分红送转方案，一规范方案身份一行。
- [MySQL additional_issue](help:MySQL%20additional_issue)：通达信增发方案，一规范方案身份一行。
- [MySQL rights_issue](help:MySQL%20rights_issue)：通达信配股方案，一规范方案身份一行。
- [MySQL security_name_change](help:MySQL%20security_name_change)：通达信公司全称与股票简称更名来源记录，共表按类型区分。
- [MySQL income_statement](help:MySQL%20income_statement)：同花顺利润表，一证券/报告期一行。
- [MySQL balance_statement](help:MySQL%20balance_statement)：同花顺资产负债表，一证券/报告期一行。
- [MySQL cashflow_statement](help:MySQL%20cashflow_statement)：同花顺现金流量表，一证券/报告期一行。
- [MySQL industry](help:MySQL%20industry)：同花顺当前行业目录，一行业一行。
- [MySQL industry_member](help:MySQL%20industry_member)：同花顺当前行业与证券关联，一行业/证券一行。
- [MySQL stock_index](help:MySQL%20stock_index)：同花顺当前指数目录和成员可用性，一来源指数一行。
- [MySQL stock_index_member](help:MySQL%20stock_index_member)：同花顺当前指数成分，一指数/来源证券编号一行。
- [MySQL stock_market_day](help:MySQL%20stock_market_day)：开盘啦七种独立证券日业务头，一类型/证券/交易日一行。
- [MySQL stock_intraday_trend](help:MySQL%20stock_intraday_trend)：开盘啦来源分钟分时事实，一证券/交易日/来源分钟一行。
- [MySQL stock_opening_auction](help:MySQL%20stock_opening_auction)：开盘啦竞价序列事实，一证券/交易日/来源序号一行。
- [MySQL stock_minute_volume](help:MySQL%20stock_minute_volume)：开盘啦分钟成交量额事实，一证券/交易日/来源分钟一行。
- [MySQL stock_intraday_trade_block](help:MySQL%20stock_intraday_trade_block)：开盘啦分笔类型化压缩块，一证券/交易日/块序号一行。
- [MySQL stock_minute_entrust](help:MySQL%20stock_minute_entrust)：开盘啦分钟委买委卖量额事实。
- [MySQL stock_large_order_trend](help:MySQL%20stock_large_order_trend)：开盘啦大单净额分钟事实。
- [MySQL stock_daily_quote](help:MySQL%20stock_daily_quote)：开盘啦历史日行情指标，一证券/交易日一行。
- [MySQL stock_daily_quote_level](help:MySQL%20stock_daily_quote_level)：开盘啦历史日盘口买卖十档，一证券/日期/买卖方/档位一行。
- [MySQL collection_state](help:MySQL%20collection_state)：统一 SQL 已确认采集状态，每 namespace/project_id 一行。
- [MySQL app_setting](help:MySQL%20app_setting)：用户正式保存的任务、网站频控、下载资源配置。

- [MySQL security_code_alias](help:MySQL%20security_code_alias)：北交所官方新旧代码关系。

### Redis 键索引

- [Redis ingest](help:Redis%20ingest)：待归档业务队列
- [Redis checkpoint](help:Redis%20checkpoint)：采集入队断点
- [Redis fingerprints](help:Redis%20fingerprints)：业务内容摘要
- [Redis fingerprint-expiry](help:Redis%20fingerprint-expiry)：摘要到期索引
- [Redis stocks-result](help:Redis%20stocks-result)：股票最近归档结果
- [Redis stocks-committed](help:Redis%20stocks-committed)：股票最近成功核验
- [Redis archive-progress](help:Redis%20archive-progress)：增量归档进度
- [Redis collection-control](help:Redis%20collection-control)：任务运行副本与采集历史
- [Redis archives](help:Redis%20archives)：归档运行记录
- [Redis archives-revision](help:Redis%20archives-revision)：归档列表查询修订号
- [Redis errors](help:Redis%20errors)：有界错误诊断样本
- [Redis errors-revision](help:Redis%20errors-revision)：错误列表查询修订号
- [Redis rate-site](help:Redis%20rate-site)：网站直连许可与全组冷却
- [Redis rate-total](help:Redis%20rate-total)：网站总频率许可
- [Redis rate-proxy](help:Redis%20rate-proxy)：网站每出口 IP 许可
- [Redis preparation-report](help:Redis%20preparation-report)：数据准备四项检查结果
- [Redis router-mapping](help:Redis%20router-mapping)：外部代理设备映射
- [Redis router-directory](help:Redis%20router-directory)：外部代理租约目录

[文档分工与更新](help:文档分工与更新)
