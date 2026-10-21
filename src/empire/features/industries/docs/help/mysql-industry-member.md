<!-- topic:数据库参考|MySQL industry_member -->
<!-- summary:同花顺当前行业与证券关联，一行业/证券一行。 -->
<!-- group:MySQL -->
# MySQL industry_member

## 用途与归属

同花顺当前行业与证券关联，一行业/证券一行。

统一归档器调用 `datasets/industries.py` 写入；`data/industries.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `industry_code` | `CHAR(6) NOT NULL` | 同花顺来源行业编号，六位字符串；与统一证券代码不同。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称；不是完整历史名称库。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (industry_code, unified_code)`
- `KEY ix_industry_security (unified_code, industry_code)`

## 读写与关联

仅在选择行业后分页读取对应成员，计数独立完整查询；成员与当前行业关联，不作历史成分。

按 industry_code 前缀查行业成员，ix_industry_security 支持证券反查；关联行业及统一证券身份，退出当前股票池不被视为永久证券消失。

关联当前 industry；移除和新增成员按完整集合事务更新，相同不写，不证明历史所属。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[同花顺当前行业](help:同花顺当前行业)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL industry](help:MySQL%20industry)
