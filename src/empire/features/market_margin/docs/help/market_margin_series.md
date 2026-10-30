<!-- topic:数据库参考|MySQL market_margin_series -->
<!-- summary:同花顺市场融资融券结构化事实与完整序列证明。 -->
<!-- group:MySQL -->
# MySQL market_margin_series

## 用途与归属

固定来源ths，任务ths-market-margin，数据集market_margin.ths_series。

## 结构与身份

| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `market_code` | `VARCHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 来源市场身份 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范全序列SHA-256 |
| `row_count` | `INT UNSIGNED NOT NULL` | 全序列条数 |
| `first_date` | `DATE NULL` | 最早来源日 |
| `last_date` | `DATE NULL` | 最新来源日 |
| `contract_version` | `INT NOT NULL` | 完整集合规范版本 |

- `PRIMARY KEY (market_code)`
- `CONSTRAINT ck_market_margin_count CHECK (row_count >= 0 AND row_count <= 10000)`
- `CONSTRAINT ck_market_margin_bounds CHECK ((row_count = 0 AND first_date IS NULL AND last_date IS NULL) OR (row_count > 0 AND first_date IS NOT NULL AND last_date IS NOT NULL AND first_date <= last_date))`

## 读写与关联

主键market_code，每个完整市场一行内容证明，与明细同事务；不是运行记录。 相同内容零业务DML，观测版本在collection_state同事务保存，旧响应不能覆盖。完整来源缩短拒绝删除。显式scripts/create_market_margin_schema.py建表，启动不迁移。Redis仅暂存消息与公共摘要；归档成功即清消息。

## 保留与恢复

长期保留市场历史，Redis丢失重核完整市场；SQL与collection_state同事务，归档失败保留消息，成功即清队。

## 维护与相关说明

建表仅由显式维护入口执行。手工修改业务前停止归档并失效对应市场摘要及覆盖证明。

[同花顺市场融资融券](help:同花顺市场融资融券)
