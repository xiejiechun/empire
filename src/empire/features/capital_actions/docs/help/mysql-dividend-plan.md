<!-- topic:数据库参考|MySQL dividend_plan -->
<!-- summary:通达信分红送转方案，一规范方案身份一行。 -->
<!-- group:MySQL -->
# MySQL dividend_plan

## 用途与归属

通达信分红送转方案，一规范方案身份一行。

统一归档器调用 `features/capital_actions/dataset.py` 写入；`features/capital_actions/query.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范来源业务身份 SHA-256，不是采集运行 ID；身份组成由对应数据契约规定。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称；不是完整历史名称库。 |
| `event_date` | `DATE NULL` | 方案报告/分红业务日期，未知可为 NULL；与除权生效日分别保存。 |
| `payload` | `JSON NOT NULL` | 规范方案 JSON：报告/登记/除权日期、每股派息/送转、实施状态和来源字段；不保存 HTTP 原文，字段由 capital_validation 校验。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务内容 SHA-256；不包含批次、页号和纯观测时间。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前入库存储版本的请求观测时刻（北京时间），用于版本排序；相同内容不刷新。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (record_key)`
- `INDEX ix_security_date (unified_code, event_date)`
- `INDEX ix_security_order ((RIGHT(unified_code,2)), unified_code, record_key)`
- `INDEX ix_event_date (event_date DESC, (RIGHT(unified_code,2)), unified_code, record_key)`

## 读写与关联

方案查询按统一证券、来源日期范围、来源状态及精确记录键筛选；平行方案独立呈现，来源日期字段不冒充公告日。

按证券/业务日期浏览或证券范围有界读取，市场顺序表达式索引用于跨市场游标；业务事件以 record_key 区分，并列方案不求和。分红现行@3身份包含证券、报告期、公告日及派息/送股/转增（身份NULL/零归一，字段实际值不改），旧@1/@2通过scripts/migrate_dividend_identity.py显式维护。复权只读声明有效方案。

历史方案保留；每股比例/现金及股份单位规范化；重复不写，来源观察版本防迟到覆盖。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[分红送转](help:分红送转)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)

范围准备读取本表完整证券单元，与同事务collection_state的业务键/规范内容摘要比较后再按事件日期投影；保留历史不删除，成员未证实不能仅按数量放行。不改字段、唯一键、索引或写入契约。

正式dividends.query的名义派息汇总复用该只读事务内的完整单元，最多20个指定证券、每证券2000条。计算按payload.ex_date闭区间筛选明确实施事件，不按浏览的event_date报告期回退规则替代除息日，也不按列表分页求和。结果不写本表、不改观察时间，预案和历史原行保留；不能识别事件关系时拒绝计算，不能删行消除歧义。
