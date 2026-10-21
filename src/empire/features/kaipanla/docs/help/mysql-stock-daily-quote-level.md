<!-- topic:数据库参考|MySQL stock_daily_quote_level -->
<!-- summary:开盘啦历史日盘口买卖十档，一证券/日期/买卖方/档位一行。 -->
<!-- group:MySQL -->
# MySQL stock_daily_quote_level

## 用途与归属

开盘啦历史日盘口买卖十档，一证券/日期/买卖方/档位一行。

统一归档器调用 `datasets/market_repository.py` 写入；`data/kaipanla_products.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `trade_date` | `DATE NOT NULL` | 来源业务交易日期，不按请求日期或自然日推算。 |
| `side` | `CHAR(1) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | b 买方、s 卖方。 |
| `level` | `TINYINT UNSIGNED NOT NULL` | 买卖档位 1～10，零价/零量档位仍保留。 |
| `price` | `DECIMAL(30,12) NOT NULL` | 来源价格数值，按规范精度保存。 |
| `source_volume` | `DECIMAL(30,12) NOT NULL` | 来源量数值；单位未确认时不转为股或手。 |
| `float_mask` | `TINYINT UNSIGNED NOT NULL` | 规范数值类型位图，保留来源整数、浮点及负零类型；不是业务状态。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code, trade_date, side, level)`
- `CONSTRAINT ck_quote_level CHECK (side IN ('b','s') AND level BETWEEN 1 AND 10)`
- `CONSTRAINT ck_quote_level_value CHECK (price>=0 AND source_volume>=0 AND float_mask<16)`

## 读写与关联

盘口档位按来源买卖档顺序展示，与证券日快照身份一致，不用缺失档位伪造零挂单。

按证券日 side/level 点查 20 档；同事务关联 stock_daily_quote 和 kind=quote 父头。买卖方/档位明确排序，零档位不删除，不据此生成全天盘口轨迹。

kind=quote 父头且关联同日 stock_daily_quote；保存 20 档，零价量仍保留，不表示全天各档变化。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_market_storage.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[历史盘口与日行情摘要](help:历史盘口与日行情摘要)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL stock_market_day](help:MySQL%20stock_market_day)、[行情事实字段与查询](help:行情事实字段与查询)
