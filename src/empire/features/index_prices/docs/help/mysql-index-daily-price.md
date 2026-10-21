<!-- topic:数据库参考|MySQL index_daily_price -->
<!-- summary:同花顺指数日线事实，按指数日期查询价格及量额。 -->
<!-- group:MySQL -->
# MySQL index_daily_price

## 用途与归属

量额质量由正式查询从有符号原值派生，不以非负SQL约束拒绝整年。已有库关闭程序、清空待归档后运行scripts/migrate_index_price_numeric_quality.py --apply显式移除旧约束，维护前后核对原业务内容，启动不迁移。

固定来源ths，采集项目ths-index-prices；统一归档器调用datasets/index_prices.py写入，data/index_prices.py提供查询。来源HTTP正文不保存。开盘、最高、最低价缺失时为NULL，非空价格仍核验；收盘与成交量为必需字段；成交额来源空值保存NULL，不根据成交量为0代填。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `index_code` | `CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 同花顺来源指数六位编号，保持1A/1B等身份，不推导股票代码。 |
| `trade_date` | `DATE NOT NULL` | 来源交易日期，仅收盘后可用记录，不推断缺日为休市。 |
| `open` | `DECIMAL(18,6) NULL` | 来源开盘指数点数，正数，最多六位小数。 |
| `high` | `DECIMAL(18,6) NULL` | 来源最高指数点数；关系矛盾保留原值并标注异常。 |
| `low` | `DECIMAL(18,6) NULL` | 来源最低指数点数，为正；关系矛盾保留原值并标注异常。 |
| `close` | `DECIMAL(18,6) NOT NULL` | 来源收盘指数点数，盘中当天不保存为收盘。 |
| `volume` | `DECIMAL(24,4) NOT NULL` | 来源成交量数值，不擅自换算特殊指数口径；负数原样保存并标量额异常，零与未知区分。 |
| `amount` | `DECIMAL(24,4) NULL` | 来源成交额人民币元，最多四位小数；负值原样保存并标量额异常，缺失为NULL，零为来源真实0。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (index_code, trade_date)`
- `KEY ix_index_price_date (trade_date, index_code)`
- `CONSTRAINT ck_index_price_code CHECK (REGEXP_LIKE(index_code, '^[0-9A-Z]{6}$'))`
- `CONSTRAINT ck_index_price_date CHECK (trade_date >= '1990-01-01')`
- `CONSTRAINT ck_index_price_ohlc CHECK (close > 0 AND (open IS NULL OR open > 0) AND (high IS NULL OR high > 0) AND (low IS NULL OR low > 0))`

## 读写与关联

范围图读取单个指数起止日期内全部日行，最多40年/15000日，超限拒绝截断；异常四价保留原值和有效收盘，明细独立分页。

日行由(index_code,trade_date)唯一；年度头由(index_code,quote_year)唯一，与实际日期集合及内容摘要绑定。单指数使用主键，跨指数日期页使用ix_index_price_date。查询页200、最多500，年度最多366行；不外键级联到当前stock_index，目录移除不删除历史。完整年与近期窗口使用同一正式写入器，同年一个摘要身份，模式和来源计数参与内容。观察代次仅防迟到覆盖，不是源站修订版本。

## 保留与恢复

MySQL持久保留历史；相同内容不执行业务DML，有效修订只写变化日期及受影响证明。统一归档成功即删待归档消息，失败保留重放；Redis丢失从SQL年度证明重新补缺，近期窗口重读。手工改SQL须停止归档并失效该来源摘要及年度证明，不清空共享Redis。

成交额缺失参与规范摘要和年度集合证明，查询显示来源未提供；准备检查按范围统计缺额，不强制来源未提供的可选成交额，依赖成交额的分析不可用。

## 维护与相关说明

scripts/create_index_price_schema.py是显式新增入口，关闭Empire、待归档0并取得维护锁，前后核对原有表数量、结构和统一状态；启动不改表，新空库init-db。普通采集不执行DDL。migrate_index_price_amount.py显式将amount列允许NULL及调整量额约束，同样要求关闭、空队列和维护锁，并核对前后所有日行、年度证明及既有状态内容。migrate_index_price_quality.py显式将价格关系约束转为质量检查，保留正价格约束；关闭Empire、空队列和维护锁下核对前后日行、年度证明及统一状态，查询派生质量标注，准备质量项不放行异常。migrate_index_price_nulls.py为旧结构三个价格列允许NULL的显式入口，遵守同一关闭、空队列和锁要求，前后核对价格及年度证明的内容摘要。

[同花顺指数历史日行情](help:同花顺指数历史日行情)、[MySQL collection_state](help:MySQL%20collection_state)
