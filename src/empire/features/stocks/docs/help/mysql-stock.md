<!-- topic:数据库参考|MySQL stock -->
<!-- summary:当前股票目录，一证券一行；同花顺主目录与新浪备用发布同一份表。 -->
<!-- group:MySQL -->
# MySQL stock

## 用途与归属

当前股票目录，一证券一行；同花顺主目录与新浪备用发布同一份表。

统一归档器调用 `datasets/stocks.py` 写入；`data/stocks.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `name` | `VARCHAR(100) NOT NULL` | 来源名称；不是完整历史名称库。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code)`

## 读写与关联

预览候选按所选数据项目查询已归档统一证券，并关联当前名称；股票概览与精确表格共享正式查询，候选最多30项。开盘啦先在证券日头有界选择身份再关联名称，避免连接全历史证券日。

按 unified_code/市场/名称有界浏览；市场从后缀解析，证券可被历史资料引用但退出现行列表不删除历史表。完整当前集合与 SQL publication 同事务。

完整集合校验后同事务替换；相同不写，不保存日快照。publication 仅记录最后实际变化批次。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[股票列表](help:股票列表)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)
