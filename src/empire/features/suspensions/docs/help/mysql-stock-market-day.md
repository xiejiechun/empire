<!-- topic:数据库参考|MySQL stock_market_day -->
<!-- summary:开盘啦七种独立证券日业务头，一类型/证券/交易日一行。 -->
<!-- group:MySQL -->
# MySQL stock_market_day

## 用途与归属

开盘啦七种独立证券日业务头，一类型/证券/交易日一行。

统一归档器调用 `datasets/market_repository.py` 写入；`data/kaipanla_products.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `kind` | `VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | trend/auction/volume/trades/entrust/large_order/quote，七项独立业务，不能互相代替。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `trade_date` | `DATE NOT NULL` | 来源业务交易日期，不按请求日期或自然日推算。 |
| `source_code` | `VARCHAR(6) CHARACTER SET ascii COLLATE ascii_bin NULL` | 来源原始证券编号；指数允许五/六位编号，不强行映射市场。 |
| `listing_date` | `DATE NOT NULL` | 来源首次上市日期；行情头中为确定采集起点的关联日期。 |
| `listing_source` | `VARCHAR(16) NOT NULL` | 上市日期的关联证据来源。 |
| `market_start` | `DATE NOT NULL` | 市场已知起点，与上市日及接口起点共同限制采集范围。 |
| `identity_extra` | `JSON NOT NULL` | 有白名单的官方证券别名证明，单字段不超过 16 KiB。 |
| `product_extra` | `JSON NOT NULL` | 有白名单的来源日统计/盘口补充，不保存完整响应，单字段不超过 16 KiB。 |
| `source_metadata` | `JSON NOT NULL` | 仅来源 time/time2/ts 元数据，单字段不超过 16 KiB。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务内容 SHA-256；不包含批次、页号和纯观测时间。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前入库存储版本的请求观测时刻（北京时间），用于版本排序；相同内容不刷新。 |
| `contract_version` | `SMALLINT UNSIGNED NOT NULL` | 现行类型化证券日存储契约，固定为 2。 |
| `point_count` | `INT UNSIGNED NOT NULL` | 该完整业务单元/块的来源点数量；仍需核对业务键集合。 |
| `key_set_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范来源业务点键集合 SHA-256，与数量共同证明完整性。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (kind, unified_code, trade_date)`
- `KEY ix_market_date (kind, trade_date, unified_code)`
- `CONSTRAINT ck_market_kind CHECK (kind IN ('trend','auction','volume','trades','entrust','large_order','quote'))`
- `CONSTRAINT ck_market_count CHECK (point_count BETWEEN 1 AND 100000)`
- `CONSTRAINT ck_market_contract CHECK (contract_version=2)`
- `CONSTRAINT ck_market_extra CHECK (JSON_STORAGE_SIZE(identity_extra)<=16384 AND JSON_STORAGE_SIZE(product_extra)<=16384 AND JSON_STORAGE_SIZE(source_metadata)<=16384)`

## 读写与关联

预览增加指定项目证券的最近/前后已归档日和完整有限单日读取；日期导航根据本项目日头，不逐日试探全年。

按 kind/unified_code/trade_date 点查单元或 ix_market_date 日期截面；轻量补缺读头，详细完整性读取对应明细并核对 point_count/key_set_hash/content_hash。七项独立状态不能相互代替。

每种数据和其明细同事务归档；独立补缺，完整日有数量和键集合摘要。历史修订按规范版本比较。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_market_storage.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[开盘啦分时及竞价](help:开盘啦分时及竞价)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[行情事实字段与查询](help:行情事实字段与查询)
