<!-- topic:数据库参考|MySQL industry -->
<!-- summary:同花顺当前行业目录，一行业一行。 -->
<!-- group:MySQL -->
# MySQL industry

## 用途与归属

同花顺当前行业目录，一行业一行。

统一归档器调用 `datasets/industries.py` 写入；`data/industries.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `industry_code` | `CHAR(6) NOT NULL` | 同花顺来源行业编号，六位字符串；与统一证券代码不同。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称；不是完整历史名称库。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (industry_code)`

## 读写与关联

目录使用正式查询返回行业及全体成员计数，证券反查保留市场；不从成员第一页在前端推导目录。

按 industry_code 定位当前行业，与 industry_member 用行业编号关联；完整当前目录和成员同事务，目录不能冒充历史行业。

完整当前集合替换，不保存历史行业快照；与 industry_member 同事务核对。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[同花顺当前行业](help:同花顺当前行业)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL industry_member](help:MySQL%20industry_member)
