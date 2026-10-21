<!-- topic:数据库参考|MySQL security_listing_event -->
<!-- summary:通达信暂停、恢复、终止上市来源事件。 -->
<!-- group:MySQL -->
# MySQL security_listing_event

## 用途与归属

通达信暂停、恢复、终止上市来源事件。

统一归档器调用 `features/listing_status/dataset.py` 写入；`features/listing_status/query.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `event_date` | `DATE NOT NULL` | 来源上市状态事件生效日期。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `event_type` | `VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | suspended 暂停上市、resumed 恢复上市、terminated 终止上市。 |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范来源业务身份 SHA-256，不是采集运行 ID；身份组成由对应数据契约规定。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称；不是完整历史名称库。 |
| `description` | `TEXT NULL` | 来源事件说明，最长 2000 字符；不推算最后交易日。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (event_date, unified_code, event_type, record_key)`
- `KEY ix_security_date (unified_code, event_date, event_type, record_key)`
- `KEY ix_type_date (event_type, event_date, unified_code, record_key)`
- `CONSTRAINT ck_listing_event_date CHECK (event_date >= '1990-12-19')`
- `CONSTRAINT ck_listing_event_type CHECK (event_type IN ('suspended', 'resumed', 'terminated'))`
- `CONSTRAINT ck_listing_event_description CHECK (description IS NULL OR CHAR_LENGTH(description) <= 2000)`

## 读写与关联

事件列表支持日期范围及类型筛选；来源说明仍按选定事件身份单独加载，列表不读取大正文。

按 unified_code/event_date 或 event_type/event_date 游标读取；暂停/恢复/终止上市三类独立。与停复牌业务不同，不能通过关联两个表自行裁定唯一交易约束。

按完整自然月事件集合验收，最大事件日不能证明覆盖；不是日常停复牌记录，不推算最后交易日。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/create_listing_event_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[暂停恢复终止上市](help:暂停恢复终止上市)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)
