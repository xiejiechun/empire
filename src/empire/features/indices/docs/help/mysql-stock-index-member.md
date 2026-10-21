<!-- topic:数据库参考|MySQL stock_index_member -->
<!-- summary:同花顺当前指数成分，一指数/来源证券编号一行。 -->
<!-- group:MySQL -->
# MySQL stock_index_member

## 用途与归属

同花顺当前指数成分，一指数/来源证券编号一行。

统一归档器调用 `datasets/indices.py` 写入；`data/indices.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `index_code` | `CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 同花顺来源指数编号，六位字母数字字符串；不能默认当作股票代码。 |
| `source_code` | `VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源原始证券编号；指数允许五/六位编号，不强行映射市场。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NULL` | 能明确市场时保存统一证券代码；不确定为 NULL，来源编号仍在 source_code 保存。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称；不是完整历史名称库。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (index_code, source_code)`
- `KEY ix_index_security (unified_code, index_code)`
- `KEY ix_index_source_security (source_code, index_code)`
- `CONSTRAINT ck_index_member_code CHECK (source_code REGEXP '^[0-9]{5,6}$')`
- `CONSTRAINT ck_index_member_unified CHECK (unified_code IS NULL OR unified_code REGEXP '^[0-9]{6}[.](SH|SZ|BJ)$')`

## 读写与关联

成员查询显式绑定所选指数，反查结合来源代码和完整证券身份防止串市场；当前成员不推导历史成员。

主键支持单指数来源成员，ix_index_security/ix_index_source_security 支持统一证券或来源编号反查；不能只用裸 source_code 猜市场，无法确定市场仍保留成员。

unified_code 不确定时为 NULL，保留 source_code，不猜市场；当前成员与父目录计数/摘要核对。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/create_index_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[同花顺当前指数及成分](help:同花顺当前指数及成分)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL stock_index](help:MySQL%20stock_index)
