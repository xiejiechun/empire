<!-- topic:数据库参考|MySQL stock_intraday_trade_block -->
<!-- summary:开盘啦分笔类型化压缩块，一证券/交易日/块序号一行。 -->
<!-- group:MySQL -->
# MySQL stock_intraday_trade_block

## 用途与归属

开盘啦分笔类型化压缩块，一证券/交易日/块序号一行。

统一归档器调用 `datasets/market_repository.py` 写入；`data/kaipanla_products.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `trade_date` | `DATE NOT NULL` | 来源业务交易日期，不按请求日期或自然日推算。 |
| `block_seq` | `INT UNSIGNED NOT NULL` | 零起块序号，按每块最多 200 点划分。 |
| `first_seq` | `INT UNSIGNED NOT NULL` | 块内首点顺序，等于 block_seq × 200。 |
| `last_seq` | `INT UNSIGNED NOT NULL` | 块内末点顺序，等于 first_seq + point_count − 1。 |
| `first_time` | `TIME(0) NOT NULL` | 块内首点来源时刻，定位时段查询边界。 |
| `last_time` | `TIME(0) NOT NULL` | 块内末点来源时刻，可与相邻块同秒。 |
| `point_count` | `SMALLINT UNSIGNED NOT NULL` | 该完整业务单元/块的来源点数量；仍需核对业务键集合。 |
| `format_version` | `SMALLINT UNSIGNED NOT NULL` | 类型化分笔块编码版本，当前为 1。 |
| `body` | `BLOB NOT NULL` | zlib 压缩的类型化来源点：时刻、数值类型位图和七个数值；不是 HTTP 原文。 |
| `block_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 压缩块正文 SHA-256，用于解码前校验。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code, trade_date, block_seq)`
- `KEY ix_trade_time (unified_code, trade_date, first_time, block_seq)`
- `CONSTRAINT ck_trade_block CHECK (format_version=1 AND point_count BETWEEN 1 AND 200 AND first_seq=block_seq*200 AND last_seq=first_seq+point_count-1 AND last_time>=first_time AND OCTET_LENGTH(body)<=24576)`

## 读写与关联

分笔预览仅读取所选时间窗的相关块，游标绑定范围及版本，保留原始seq与同秒多笔；概览不冒充全天统计。

按证券日 block_seq 页序及 ix_trade_time 定位时段，解码有界块返回最多 200 点；同秒跨块多笔保留。游标绑定父头版本，来源修订后旧游标失效；不支持 SQL 任意逐笔字段筛选。

kind=trades 父头；每块最多 200 点，正文最多 24576 字节，解码最多 12400 字节。同秒跨块多笔保留，不能直接用 SQL 逐笔任意字段聚合。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_market_storage.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[开盘啦分时及竞价](help:开盘啦分时及竞价)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL stock_market_day](help:MySQL%20stock_market_day)、[行情事实字段与查询](help:行情事实字段与查询)
