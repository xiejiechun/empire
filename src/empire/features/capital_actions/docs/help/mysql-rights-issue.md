<!-- topic:数据库参考|MySQL rights_issue -->
<!-- summary:通达信配股方案，一规范方案身份一行。 -->
<!-- group:MySQL -->
# MySQL rights_issue

## 用途与归属

通达信配股方案，一规范方案身份一行。

统一归档器调用 `features/capital_actions/dataset.py` 写入；`features/capital_actions/query.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范来源业务身份 SHA-256，不是采集运行 ID；身份组成由对应数据契约规定。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称；不是完整历史名称库。 |
| `event_date` | `DATE NULL` | 来源配股业务/除权日期，未知可为 NULL。 |
| `payload` | `JSON NOT NULL` | 规范方案 JSON：配股/登记/除权日期、每股配股数、配股价及来源字段；缺值不补造，字段由 capital_validation 校验。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务内容 SHA-256；不包含批次、页号和纯观测时间。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前入库存储版本的请求观测时刻（北京时间），用于版本排序；相同内容不刷新。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (record_key)`
- `INDEX ix_security_date (unified_code, event_date)`
- `INDEX ix_security_order ((RIGHT(unified_code,2)), unified_code, record_key)`
- `INDEX ix_event_date (event_date DESC, (RIGHT(unified_code,2)), unified_code, record_key)`

## 读写与关联

配股方案查询按证券、日期范围、状态和记录键筛选；复权事件链接直接定位原方案，不裁定多个方案的优先级。

按证券、日期和 record_key 有界浏览；同登记日不同认购代码/缴款起日分别保存。复权依有效除权日和每股配股数/价使用，不把发行日当除权日。

保留历史和有效修订；每十股配股数换为每股，不能拿发行日冒充除权日。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[配股](help:配股)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)
