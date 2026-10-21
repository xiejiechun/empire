<!-- topic:数据库参考|MySQL stock_minute_entrust -->
<!-- summary:开盘啦分钟委买委卖量额事实。 -->
<!-- group:MySQL -->
# MySQL stock_minute_entrust

## 用途与归属

开盘啦分钟委买委卖量额事实。

统一归档器调用 `datasets/market_repository.py` 写入；`data/kaipanla_products.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `trade_date` | `DATE NOT NULL` | 来源业务交易日期，不按请求日期或自然日推算。 |
| `seq` | `INT UNSIGNED NOT NULL` | 零起的来源点顺序；竞价按它区分同分钟多点。 |
| `source_time` | `TIME(0) NOT NULL` | 来源真实日内时刻；分钟数据不填造缺失点。 |
| `float_mask` | `SMALLINT UNSIGNED NOT NULL` | 规范数值类型位图，保留来源整数、浮点及负零类型；不是业务状态。 |
| `buy_volume` | `DECIMAL(30,12) NOT NULL` | 来源委买量数值，保留来源单位。 |
| `sell_volume` | `DECIMAL(30,12) NOT NULL` | 来源委卖量数值，保留来源单位。 |
| `buy_turnover` | `DECIMAL(30,12) NOT NULL` | 来源委买额数值，保留来源单位。 |
| `sell_turnover` | `DECIMAL(30,12) NOT NULL` | 来源委卖额数值，保留来源单位。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code, trade_date, source_time)`
- `KEY ix_minute_date (trade_date, source_time, unified_code)`
- `CONSTRAINT ck_entrust_seq CHECK (seq<241)`
- `CONSTRAINT ck_entrust_mask CHECK (float_mask<256)`

## 读写与关联

完整有限证券日序列供图表读取，明细另分页；真实时间及来源seq保留，竞价同分钟按序号检查，午休和缺值断开，不把前200点当全天。

按证券日 source_time 分页，ix_minute_date 用于分钟截面；kind=entrust 关联父头，不推导来源未提供的逐笔委托。

kind=entrust 父头；量额不冒充逐单委托明细，按来源分钟保留。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_market_storage.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[开盘啦分时及竞价](help:开盘啦分时及竞价)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL stock_market_day](help:MySQL%20stock_market_day)、[行情事实字段与查询](help:行情事实字段与查询)
