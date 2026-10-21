<!-- topic:数据库参考|MySQL income_statement -->
<!-- summary:同花顺利润表，一证券/报告期一行。 -->
<!-- group:MySQL -->
# MySQL income_statement

## 用途与归属

同花顺利润表，一证券/报告期一行。

统一归档器调用 `features/financial_statements/dataset.py` 写入；`features/financial_statements/query.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `report_date` | `DATE NOT NULL` | 报表报告期，不是公告日或历史可用日。 |
| `payload` | `JSON NOT NULL` | 规范完整报表 JSON：证券/报告期、科目行、原单位及舍入精度；来源缺值为 JSON null，不保存 HTTP 原文。SQL 不是传输层共享科目矩阵。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务内容 SHA-256；不包含批次、页号和纯观测时间。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前入库存储版本的请求观测时刻（北京时间），用于版本排序；相同内容不刷新。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code, report_date)`
- `INDEX ix_report_date (report_date DESC, (RIGHT(unified_code,2)), unified_code)`

## 读写与关联

选定统一证券的完整报告历史有界读取最多500期，供累计利润矩阵和趋势；列表分页与报告历史分别查询，不将第一页当全部报告。

按 unified_code/report_date 点查报告或分页列表；ix_report_date 支持报告期倒序和市场/证券顺序。查询只用本表现行 payload，历史证券即使退出 stock 仍可保留；报告期不代表公告可用时间。

report 口径，保留历史报告期；有效修订替换该期，相同不写。没有公告日，不证明历史信号可用日。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_business_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[同花顺三大报表](help:同花顺三大报表)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)
