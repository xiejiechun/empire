<!-- topic:数据库参考|MySQL stock_daily_quote -->
<!-- summary:开盘啦历史日行情指标，一证券/交易日一行。 -->
<!-- group:MySQL -->
# MySQL stock_daily_quote

## 用途与归属

开盘啦历史日行情指标，一证券/交易日一行。

统一归档器调用 `datasets/market_repository.py` 写入；`data/kaipanla_products.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `trade_date` | `DATE NOT NULL` | 来源业务交易日期，不按请求日期或自然日推算。 |
| `float_mask` | `BIGINT UNSIGNED NOT NULL` | 规范数值类型位图，保留来源整数、浮点及负零类型；不是业务状态。 |
| `present_mask` | `BIGINT UNSIGNED NOT NULL` | 可选字段是否出现的位图，区分缺字段、显式 NULL 与零。 |
| `time` | `DECIMAL(30,12) NULL` | 来源 real.time 数值，含义未确认，不转换为时间戳。 |
| `up_px` | `DECIMAL(30,12) NULL` | 来源涨停价格数值。 |
| `avg_px` | `DECIMAL(30,12) NULL` | 来源均价数值。 |
| `low_px` | `DECIMAL(30,12) NULL` | 来源最低价数值。 |
| `down_px` | `DECIMAL(30,12) NULL` | 来源跌停价格数值。 |
| `high_px` | `DECIMAL(30,12) NULL` | 来源最高价数值。 |
| `last_px` | `DECIMAL(30,12) NULL` | 来源最新/收盘价数值。 |
| `open_px` | `DECIMAL(30,12) NULL` | 来源开盘价数值。 |
| `pe_rate` | `DECIMAL(30,12) NULL` | 来源市盈率数值，口径按来源。 |
| `jtPeRate` | `DECIMAL(30,12) NULL` | 来源静态市盈率数值。 |
| `TTMPeRate` | `DECIMAL(30,12) NULL` | 来源 TTM 市盈率数值。 |
| `amount_in` | `DECIMAL(30,12) NULL` | 来源 amount_in 数值；单位未确认不换算。 |
| `amplitude` | `DECIMAL(30,12) NULL` | 来源振幅数值，保留来源比例单位。 |
| `px_change` | `DECIMAL(30,12) NULL` | 来源价格变动数值。 |
| `vol_ratio` | `DECIMAL(30,12) NULL` | 来源量比数值。 |
| `amount_out` | `DECIMAL(30,12) NULL` | 来源 amount_out 数值；单位未确认不换算。 |
| `dyn_pb_rate` | `DECIMAL(30,12) NULL` | 来源动态市净率数值。 |
| `phcj_volume` | `DECIMAL(30,12) NULL` | 来源盘后成交量数值，保留来源单位。 |
| `entrust_rate` | `DECIMAL(30,12) NULL` | 来源委比数值，保留来源比例单位。 |
| `market_value` | `DECIMAL(30,12) NULL` | 来源总市值数值，保留来源单位。 |
| `total_amount` | `DECIMAL(30,12) NULL` | 来源 total_amount 数值，保留来源单位。 |
| `total_shares` | `DECIMAL(30,12) NULL` | 来源总股本数值，保留来源单位。 |
| `phcj_turnover` | `DECIMAL(30,12) NULL` | 来源盘后成交额数值，保留来源单位。 |
| `px_change_rate` | `DECIMAL(30,12) NULL` | 来源涨跌幅数值，保留来源比例单位。 |
| `total_turnover` | `DECIMAL(30,12) NULL` | 来源总成交额数值，保留来源单位。 |
| `turnover_ratio` | `DECIMAL(30,12) NULL` | 来源换手率数值，保留来源比例单位。 |
| `circulation_value` | `DECIMAL(30,12) NULL` | 来源流通市值数值，保留来源单位。 |
| `circulation_amount` | `DECIMAL(30,12) NULL` | 来源 circulation_amount 数值，保留来源单位。 |
| `actualcirculation_value` | `DECIMAL(30,12) NULL` | 来源实际流通市值数值，保留来源单位。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code, trade_date)`
- `KEY ix_quote_date (trade_date, unified_code)`
- `CONSTRAINT ck_quote_mask CHECK (float_mask<288230376151711744 AND present_mask<536870912)`

## 读写与关联

盘口页面只读所选证券日的类型化快照，独立可选分时图由对应分时查询加载；未采集和失败分别提示。

证券日点查、ix_quote_date 日期截面和有界字段投影；kind=quote 关联父头，stock_daily_quote_level 保存同日 20 档。可选空/缺/零按 present_mask 还原，单位未确认不转换。

kind=quote 父头；不是实时更新行情，不等于全天盘口轨迹。present_mask 区分缺失/显式空/零，float_mask 保留规范数值类型。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_market_storage.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[历史盘口与日行情摘要](help:历史盘口与日行情摘要)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)、[MySQL stock_market_day](help:MySQL%20stock_market_day)、[行情事实字段与查询](help:行情事实字段与查询)
