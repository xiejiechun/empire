# 数据库参考与文档职责

## 查阅入口

程序：**说明文档 → 数据库参考 → MySQL / Redis**。可搜索真实表名或键名；每项都有用途与归属、结构与身份、读写与关联、保留与恢复、维护与相关说明。

正式字段/键字典只维护在 [离线说明正文](../src/empire/plugins/ui/storage_reference.md)，程序直接加载同一资源。本文是仓库导航，不复制另一份字段字典。MySQL 类型/主键/索引/约束与 [现行 DDL](../sql/schema.sql) 逐表核对；Redis 命名与实际源码逐项关联，见 [覆盖登记](documentation-coverage.json)。

业务表归属、来源许可和查询主键的机器登记见 [SQL 归属资源](../sql/business-schema.json)。它与 [物理结构契约](../sql/schema-contract.json) 分工：前者保留数据集表组及显式维护表顺序，后者保存字段、索引和约束。维护表清单不等于全部物理表，不能用 DDL 全集自动补齐。公共存储和业务查询读取同一归属资源，新增或调整表组通过 [设计门禁](../scripts/verify_database_design.py) 核对；不会自动改库。

## 文档分工

| 内容 | 正式位置 | 同步负责人 |
| --- | --- | --- |
| 使用入口、动作、保存与生效 | 程序日常操作/故障处理；桌面指南提供概览 | 页面或流程开发者 |
| 业务字段意义、范围、单位、日期、用途和生命周期 | 程序数据说明；来源专项指南提供完整来源契约 | 采集/查询开发者 |
| 每张表、每类键的结构、身份、索引、拥有者、清理与恢复 | 程序数据库参考（同一离线正文） | 数据集或公共存储服务开发者 |
| 架构、协议、迁移执行与测试要求 | 技术参考及 docs 专项指南 | 公共基础设施/来源开发者 |
| 实际验收、动态采集范围和发布身份 | docs/evidence，implementation-status 汇总 | 验收与交付执行者 |

同一功能实现者负责受影响说明的闭环更新；业务表结构改造另遵循 [设计准入](database-design-standard.md)。正式维护步骤见 [说明文档维护](documentation-maintenance.md)，执行入口见 [开发流程](development-workflow.md)。

## MySQL 逐表索引

| 对象（点击打开正式条目） | 职责 |
| --- | --- |
| [stock](../src/empire/plugins/ui/storage_reference.md#mysql-stock) | 当前股票目录，一证券一行；同花顺主目录与新浪备用发布同一份表。 |
| [stock_listing](../src/empire/plugins/ui/storage_reference.md#mysql-stock_listing) | 同花顺首次上市与发行资料，一证券一行。 |
| [security_listing_event](../src/empire/plugins/ui/storage_reference.md#mysql-security_listing_event) | 通达信暂停、恢复、终止上市来源事件。 |
| [finance_news](../src/empire/plugins/ui/storage_reference.md#mysql-finance_news) | 新浪历史财经快讯，一来源新闻 ID 一行。 |
| [trade_calendar](../src/empire/plugins/ui/storage_reference.md#mysql-trade_calendar) | 巨潮自然日日历，交易与休市都显式保存。 |
| [suspension_event](../src/empire/plugins/ui/storage_reference.md#mysql-suspension_event) | 通达信历史停复牌完整来源记录，不裁定唯一交易约束。 |
| [suspension_source_date](../src/empire/plugins/ui/storage_reference.md#mysql-suspension_source_date) | 停复牌来源记录与实际查询日历日期的多对多关联。 |
| [dividend_plan](../src/empire/plugins/ui/storage_reference.md#mysql-dividend_plan) | 通达信分红送转方案，一规范方案身份一行；现行@3金额键NULL/零归一，原业务值保留。 |
| [additional_issue](../src/empire/plugins/ui/storage_reference.md#mysql-additional_issue) | 通达信增发方案，一规范方案身份一行。 |
| [rights_issue](../src/empire/plugins/ui/storage_reference.md#mysql-rights_issue) | 通达信配股方案，一规范方案身份一行。 |
| [security_name_change](../src/empire/plugins/ui/storage_reference.md#mysql-security_name_change) | 通达信公司全称与股票简称更名来源记录，共表按类型区分。 |
| [income_statement](../src/empire/plugins/ui/storage_reference.md#mysql-income_statement) | 同花顺利润表，一证券/报告期一行。 |
| [balance_statement](../src/empire/plugins/ui/storage_reference.md#mysql-balance_statement) | 同花顺资产负债表，一证券/报告期一行。 |
| [cashflow_statement](../src/empire/plugins/ui/storage_reference.md#mysql-cashflow_statement) | 同花顺现金流量表，一证券/报告期一行。 |
| [industry](../src/empire/plugins/ui/storage_reference.md#mysql-industry) | 同花顺当前行业目录，一行业一行。 |
| [industry_member](../src/empire/plugins/ui/storage_reference.md#mysql-industry_member) | 同花顺当前行业与证券关联，一行业/证券一行。 |
| [stock_index](../src/empire/plugins/ui/storage_reference.md#mysql-stock_index) | 同花顺当前指数目录和成员可用性，一来源指数一行。 |
| [stock_index_member](../src/empire/plugins/ui/storage_reference.md#mysql-stock_index_member) | 同花顺当前指数成分，一指数/来源证券编号一行。 |
| [stock_market_day](../src/empire/plugins/ui/storage_reference.md#mysql-stock_market_day) | 开盘啦七种独立证券日业务头，一类型/证券/交易日一行。 |
| [stock_intraday_trend](../src/empire/plugins/ui/storage_reference.md#mysql-stock_intraday_trend) | 开盘啦来源分钟分时事实，一证券/交易日/来源分钟一行。 |
| [stock_opening_auction](../src/empire/plugins/ui/storage_reference.md#mysql-stock_opening_auction) | 开盘啦竞价序列事实，一证券/交易日/来源序号一行。 |
| [stock_minute_volume](../src/empire/plugins/ui/storage_reference.md#mysql-stock_minute_volume) | 开盘啦分钟成交量额事实，一证券/交易日/来源分钟一行。 |
| [stock_intraday_trade_block](../src/empire/plugins/ui/storage_reference.md#mysql-stock_intraday_trade_block) | 开盘啦分笔类型化压缩块，一证券/交易日/块序号一行。 |
| [stock_minute_entrust](../src/empire/plugins/ui/storage_reference.md#mysql-stock_minute_entrust) | 开盘啦分钟委买委卖量额事实。 |
| [stock_large_order_trend](../src/empire/plugins/ui/storage_reference.md#mysql-stock_large_order_trend) | 开盘啦大单净额分钟事实。 |
| [stock_daily_quote](../src/empire/plugins/ui/storage_reference.md#mysql-stock_daily_quote) | 开盘啦历史日行情指标，一证券/交易日一行。 |
| [stock_daily_quote_level](../src/empire/plugins/ui/storage_reference.md#mysql-stock_daily_quote_level) | 开盘啦历史日盘口买卖十档，一证券/日期/买卖方/档位一行。 |
| [collection_state](../src/empire/plugins/ui/storage_reference.md#mysql-collection_state) | 统一 SQL 已确认采集状态，每 namespace/project_id 一行。 |
| [app_setting](../src/empire/plugins/ui/storage_reference.md#mysql-app_setting) | 用户正式保存的任务、网站频控、下载资源配置。 |

## Redis 逐键索引

| 对象（点击打开正式条目） | 实际键模板 |
| --- | --- |
| [ingest](../src/empire/plugins/ui/storage_reference.md#redis-ingest) | `<namespace>:ingest` |
| [checkpoint](../src/empire/plugins/ui/storage_reference.md#redis-checkpoint) | `<namespace>:checkpoint:<job_key>` |
| [fingerprints](../src/empire/plugins/ui/storage_reference.md#redis-fingerprints) | `<namespace>:archive:fingerprints:v1:<dataset>:<source>` |
| [fingerprint-expiry](../src/empire/plugins/ui/storage_reference.md#redis-fingerprint-expiry) | `<namespace>:archive:fingerprints:v1:<dataset>:<source>:expiry` |
| [stocks-result](../src/empire/plugins/ui/storage_reference.md#redis-stocks-result) | `<namespace>:stocks:result:<source>` |
| [stocks-committed](../src/empire/plugins/ui/storage_reference.md#redis-stocks-committed) | `<namespace>:stocks:committed:<source>` |
| [archive-progress](../src/empire/plugins/ui/storage_reference.md#redis-archive-progress) | `<namespace>:archive:progress:<job_key>` |
| [collection-control](../src/empire/plugins/ui/storage_reference.md#redis-collection-control) | `<namespace>:collection:control:v1` |
| [archives](../src/empire/plugins/ui/storage_reference.md#redis-archives) | `<namespace>:collection:archives:<project_id>` |
| [archives-revision](../src/empire/plugins/ui/storage_reference.md#redis-archives-revision) | `<namespace>:collection:archives-revision:<project_id>` |
| [errors](../src/empire/plugins/ui/storage_reference.md#redis-errors) | `<namespace>:collection:errors:<project_id>` |
| [errors-revision](../src/empire/plugins/ui/storage_reference.md#redis-errors-revision) | `<namespace>:collection:errors-revision:<project_id>` |
| [rate-site](../src/empire/plugins/ui/storage_reference.md#redis-rate-site) | `<namespace>:rate:<group>` |
| [rate-total](../src/empire/plugins/ui/storage_reference.md#redis-rate-total) | `<namespace>:rate:<group>:total` |
| [rate-proxy](../src/empire/plugins/ui/storage_reference.md#redis-rate-proxy) | `<namespace>:rate:<group>:proxy:<exit_ip_hash>` |
| [preparation-report](../src/empire/plugins/ui/storage_reference.md#redis-preparation-report) | `<namespace>:preparation:report:<scope_digest>` |
| [router-mapping](../src/empire/plugins/ui/storage_reference.md#redis-router-mapping) | `router:proxies:by-code` |
| [router-directory](../src/empire/plugins/ui/storage_reference.md#redis-router-directory) | `router:proxies:device` |

## 边界与维护

Redis 的两类 RouterProxy 键由外部生产者拥有，Empire 只读。其他条目中的 namespace 来自配置，表/键清单描述源码现行契约，不宣称现场库已执行新增迁移。Redis 纯内存，服务重启会丢失消息、断点和记录；MySQL 已归档数据与用户配置持久保存。凭据不进入本参考。

文档门禁拒绝遗漏表、遗漏本表字段/主键/索引/约束、遗漏现有命名方式新增的 Redis 键构造、没有逐项归属或过期审阅。自动语法覆盖不能替代内容语义审阅；新键构造方式必须同步扩充检查，不得只刷新登记摘要。

北交所历史新旧代码关系见[bse代码映射](bse-code-mapping.md)，独立security_code_alias保存正式关系，不根据股票尾号猜测。

指数日行情采用index_daily_price事实和index_price_year年度完整证明，由独立同花顺项目归档，不把日行装入JSON。open/high/low允许来源缺值为NULL，close/volume仍必需，amount来源缺失为NULL；显式维护入口为scripts/migrate_index_price_nulls.py，既有内容和索引保持。字段及查询预算见[指数行情说明](ths-index-prices.md)。

指数来源价格关系矛盾保留原值：scripts/migrate_index_price_quality.py仅显式调整ck_index_price_ohlc为正价格约束，已有内容/索引/证明保持。正式查询派生价格质量标注，数据准备质量项检查所选范围异常，完整集合证明不等于四价质量通过。

指数成交额缺失由scripts/migrate_index_price_amount.py显式维护，已有事实与证明保持；字段、两条正式日期查询和索引不变，空金额不推断为0，来源修订按既有版本归档。

[security_st_event](../src/empire/plugins/ui/storage_reference.md#mysql-security_st_event)：实施ST与撤销ST结构化来源事件，两个项目共表。

指数来源负成交量/成交额按有符号DECIMAL原样存储，正式查询派生量额异常；scripts/migrate_index_price_numeric_quality.py显式移除旧非负约束，持锁及队列0后核对迁移前后内容。主键、索引及容量不变，详见[指数行情说明](ths-index-prices.md)。

东方财富股票回购：`eastmoney-repurchases`任务与`stock_repurchase_plan`正式表，数据目录按需打开方案列表及详情；固定2000ms、每日18:00全量核验。字段、生命周期、显式建表和容量证据见[股票回购](eastmoney-repurchases.md)。回购完成不推断注销。

## 通达信财报解读五项（2026-10-12）

业绩预告、快报、披露时间、报告及股东户数分别登记独立任务、结构化表、查询和按需数据页面。每页10000已实测；四报告按季度完整响应并行预取，户数按证券历史预取，按序校验入队，整轮后等待归档。实际已归档进度与最终部署见带日期证据，不以接口支持范围冒充采完。操作、字段、恢复及限制见[通达信财报解读](tdx-performance.md)。

新增正式表：earnings_forecast, earnings_quick, earnings_disclosure, earnings_report, shareholder_count，逐字段/索引参考程序内同名MySQL主题。

持有人逐表条目：[holder_report](../src/empire/plugins/ui/storage_reference.md#mysql-holder_report)（报告头）、[holder_member](../src/empire/plugins/ui/storage_reference.md#mysql-holder_member)（当前/退出成员）。来源与显式维护见[持有人说明](ths-holders.md)。

## shareholder_change

固定来源通达信，重要股东持股变动完整月市场当前事实。

| 字段 | SQL 类型与空值 | 含义 |
| --- | --- | --- |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范事实及重复序号SHA-256身份；完整月份修订时允许改变。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 证券统一身份，固定来源通达信。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源证券简称。 |
| `data_month` | `DATE NOT NULL` | 请求月份第一天；验证变动截止日所属月份。 |
| `change_end` | `DATE NOT NULL` | 来源T003变动截止日。 |
| `change_start` | `VARCHAR(10) NULL` | 来源T013开始日期；严格保存YYYY-MM-DD或YYYY-MM精度，空值未知，不补造具体日。 |
| `announcement_date` | `DATE NULL` | 来源T004公告日；空或未来不证明当时已知。 |
| `actor` | `VARCHAR(512) NOT NULL` | 来源T005变动人。 |
| `price` | `DECIMAL(28,8) NULL` | 来源T006成交均价，元/股，可空。 |
| `shares_changed` | `DECIMAL(28,8) NULL` | 来源T007带符号变动数量，股；源端NULL保留并在质量检查限制使用。 |
| `shares_after` | `DECIMAL(28,8) NULL` | 来源T008变动后持股，股，可空。 |
| `reason` | `VARCHAR(512) NULL` | 来源T009变动原因，可空。 |
| `leader` | `VARCHAR(512) NULL` | 来源T010领导人姓名，可空。 |
| `position` | `VARCHAR(512) NULL` | 来源T011职务，可空。 |
| `relationship` | `VARCHAR(512) NULL` | 来源T012与领导人关系，可空。 |
| `occurrence` | `SMALLINT UNSIGNED NOT NULL` | 相同来源事实出现序号1～9999，不是稳定事件ID。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整规范业务行SHA-256。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本观测时间，北京时间DATETIME。 |

- `PRIMARY KEY (record_key)`：完整月份/证券/日期查询和来源契约约束。
- `KEY ix_month (data_month,unified_code,record_key)`：完整月份/证券/日期查询和来源契约约束。
- `KEY ix_security_date (unified_code,change_end,record_key)`：完整月份/证券/日期查询和来源契约约束。
- `KEY ix_date (change_end,unified_code,record_key)`：完整月份/证券/日期查询和来源契约约束。
- `CONSTRAINT ck_change_month CHECK (DAYOFMONTH(data_month)=1 AND YEAR(data_month)=YEAR(change_end) AND MONTH(data_month)=MONTH(change_end))`：完整月份/证券/日期查询和来源契约约束。
- `CONSTRAINT ck_change_dates CHECK (change_start IS NULL OR (change_start REGEXP '^[0-9]{4}-[0-9]{2}(-[0-9]{2})?$' AND change_start<=CAST(change_end AS CHAR) COLLATE utf8mb4_unicode_ci))`：完整月份/证券/日期查询和来源契约约束。
- `CONSTRAINT ck_change_shares CHECK (shares_after IS NULL OR shares_after>=0)`：完整月份/证券/日期查询和来源契约约束。
- `CONSTRAINT ck_change_occurrence CHECK (occurrence BETWEEN 1 AND 9999)`：完整月份/证券/日期查询和来源契约约束。

对应单一采集、归档与查询路径；集合证明存collection_state，摘要/断点/错误和成功清队沿用现有共享键。详见[重要股东持股变动](tdx-shareholder-changes.md)。

## restricted_share_unlock

大小非解禁数据集unlocks.tdx_month，固定tdx；列表事实与共享请求组明细分表，完整月市场统一事务。

| 字段 | SQL类型与空值 | 含义 |
| --- | --- | --- |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整来源事实及相同事实出现序号的SHA-256身份。 |
| `group_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 证券、解禁日期、来源原因代码的共享明细请求组；不等于独占列表事件ID。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源sc/code证券，沪深北统一身份。 |
| `unlock_date` | `DATE NOT NULL` | 列表T003解禁日期；不是公告可用日期。 |
| `reason_code` | `VARCHAR(128) NOT NULL` | 列表T006来源请求原因代码，明细请求必需。 |
| `name` | `VARCHAR(100) NULL` | 列表name来源简称，可空。 |
| `industry` | `VARCHAR(200) NULL` | 列表hyname来源当前行业，不代表历史行业。 |
| `reason` | `VARCHAR(1024) NULL` | 列表sT006或明细T006原因说明，可空。 |
| `shares` | `DECIMAL(28,8) NULL` | jjsl万股精确乘10000转股；未知NULL，0保留来源零。 |
| `total_shares` | `DECIMAL(28,8) NULL` | T010万股转股；仅来源提供比例基数，不保证解禁当日股本。 |
| `occurrence` | `SMALLINT UNSIGNED NOT NULL` | 相同规范事实的来源出现序号1～65535；允许合法重复。 |
| `detail_status` | `VARCHAR(16) NOT NULL` | present或source_empty；请求失败不能写成source_empty。 |
| `detail_count` | `INT UNSIGNED NOT NULL` | 共享请求组实际明细条数；并列列表不能据此倍乘明细。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务事实内容SHA-256。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本的观测时间，北京时间DATETIME(6)，不是来源公告时间。 |

- `PRIMARY KEY (record_key)`：来源身份、数量或正式查询约束。
- `KEY ix_group (group_key,record_key)`：来源身份、数量或正式查询约束。
- `KEY ix_security_date (unified_code,unlock_date,record_key)`：来源身份、数量或正式查询约束。
- `KEY ix_date (unlock_date,unified_code,record_key)`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_security CHECK (unified_code REGEXP '^[0-9]{6}\\.(SH|SZ|BJ)$')`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_shares CHECK (shares>=0 AND total_shares>=0)`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_occurrence CHECK (occurrence BETWEEN 1 AND 65535)`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_detail CHECK ((detail_status='present' AND detail_count BETWEEN 1 AND 10000) OR (detail_status='source_empty' AND detail_count=0))`：来源身份、数量或正式查询约束。

查询/恢复/显式维护见[大小非解禁说明](tdx-unlocks.md)。

## restricted_share_unlock_detail

大小非解禁数据集unlocks.tdx_month，固定tdx；列表事实与共享请求组明细分表，完整月市场统一事务。

| 字段 | SQL类型与空值 | 含义 |
| --- | --- | --- |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 完整来源事实及相同事实出现序号的SHA-256身份。 |
| `group_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 证券、解禁日期、来源原因代码的共享明细请求组；不等于独占列表事件ID。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源sc/code证券，沪深北统一身份。 |
| `unlock_date` | `DATE NOT NULL` | 列表T003解禁日期；不是公告可用日期。 |
| `reason_code` | `VARCHAR(128) NOT NULL` | 列表T006来源请求原因代码，明细请求必需。 |
| `holder` | `VARCHAR(512) NOT NULL` | 明细T007股东名称，必需；来源没有稳定股东ID。 |
| `reason` | `VARCHAR(1024) NULL` | 列表sT006或明细T006原因说明，可空。 |
| `shares` | `DECIMAL(28,8) NULL` | jjsl万股精确乘10000转股；未知NULL，0保留来源零。 |
| `occurrence` | `SMALLINT UNSIGNED NOT NULL` | 相同规范事实的来源出现序号1～65535；允许合法重复。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务事实内容SHA-256。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本的观测时间，北京时间DATETIME(6)，不是来源公告时间。 |

- `PRIMARY KEY (group_key,record_key)`：来源身份、数量或正式查询约束。
- `KEY ix_date (unlock_date,unified_code,record_key)`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_member_security CHECK (unified_code REGEXP '^[0-9]{6}\\.(SH|SZ|BJ)$')`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_member_shares CHECK (shares>=0)`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_member_occurrence CHECK (occurrence BETWEEN 1 AND 65535)`：来源身份、数量或正式查询约束。
- `CONSTRAINT ck_unlock_holder CHECK (CHAR_LENGTH(TRIM(holder))>0)`：来源身份、数量或正式查询约束。

查询/恢复/显式维护见[大小非解禁说明](tdx-unlocks.md)。

## restricted_share_unlock_industry

## 用途与归属
数据集unlocks.tdx_industry_month，固定tdx，采集项目tdx-unlock-industries；统一归档与unlock_industries.tdx_query唯一正式路径。

## 结构与身份
| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `unlock_month` | `DATE NOT NULL` | 来源解禁月份固定1日，主键 |
| `industry` | `VARCHAR(200) NOT NULL` | 来源行业名，主键；没有来源行业代码 |
| `basis_date` | `DATE NOT NULL` | 目录mxt估值基准日 |
| `shares` | `DECIMAL(28,8) NULL` | T003万股转股，NULL未知 |
| `unlock_value` | `DECIMAL(28,8) NULL` | T004万元转元，NULL未知 |
| `market_cap` | `DECIMAL(28,8) NULL` | MarketCap行业总市值，元，NULL未知 |
| `negotiable_cap` | `DECIMAL(28,8) NULL` | NegotiableCap行业流通市值，元，NULL未知 |
| `market_percent` | `DECIMAL(28,8) NULL` | zszbl百分数，NULL未知 |
| `float_percent` | `DECIMAL(28,8) NULL` | ltszbl百分数，NULL未知 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范月行业内容SHA-256 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储版本观测时间，北京时间 |

## 读写与关联
`PRIMARY KEY (unlock_month,industry)`支持月份范围与完整月；`KEY ix_industry_month (industry,unlock_month)`支持行业历史。

`CONSTRAINT ck_unlock_industry_month CHECK (DAY(unlock_month)=1)`固定月份首日；`CONSTRAINT ck_unlock_industry_name CHECK (CHAR_LENGTH(TRIM(industry))>0)`保证行业非空；`CONSTRAINT ck_unlock_industry_values CHECK (shares>=0 AND unlock_value>=0 AND market_cap>=0 AND negotiable_cap>=0 AND market_percent>=0 AND float_percent>=0)`拒绝负值。单页200，单月500，当前目录120月；完整证明在collection_state同项目一行。

## 保留与恢复
完整月事务接收修订并删除本月撤回行业；目录外已有月份保留。相同内容零业务DML，旧基准/旧观测不覆盖。可信摘要免SQL；成功清队和SQL后重放由统一归档执行。显式建表scripts/create_unlock_industry_schema.py，启动不DDL，不清共享Redis。

## 维护与相关说明
[大小非解禁行业](tdx-unlock-industries.md)

同花顺持有人按来源质量类型保存：holder_report.quality_flags为结构化位标记，当期比例及定期汇总明确横线保存NULL；汇总矛盾保留原值。集合覆盖和质量限制分别查询，scripts/migrate_holder_source_rows.py显式升级contract/schema4并保留来源事实及观测版本。当期/退出数量及精度允许同时NULL并分别标记，未来报告期保留源日期及观察日质量标记；结构及身份仍严格，见[股东研究说明](ths-holders.md)。

## 公司资本运作（同花顺）

- [capital_funding](../src/empire/plugins/ui/storage_reference.md#mysql-capital_funding)：1类结构化来源事实，见逐字段正式字典。
- [capital_project](../src/empire/plugins/ui/storage_reference.md#mysql-capital_project)：2类结构化来源事实，见逐字段正式字典。
- [capital_transaction](../src/empire/plugins/ui/storage_reference.md#mysql-capital_transaction)：3类结构化来源事实，见逐字段正式字典。
- [capital_equity_summary](../src/empire/plugins/ui/storage_reference.md#mysql-capital_equity_summary)：4类结构化来源事实，见逐字段正式字典。
- [capital_equity_position](../src/empire/plugins/ui/storage_reference.md#mysql-capital_equity_position)：5类结构化来源事实，见逐字段正式字典。
- [capital_ipo](../src/empire/plugins/ui/storage_reference.md#mysql-capital_ipo)：6类结构化来源事实，见逐字段正式字典。
- [capital_encumbrance](../src/empire/plugins/ui/storage_reference.md#mysql-capital_encumbrance)：7类结构化来源事实，见逐字段正式字典。
- [capital_release](../src/empire/plugins/ui/storage_reference.md#mysql-capital_release)：8类结构化来源事实，见逐字段正式字典。
