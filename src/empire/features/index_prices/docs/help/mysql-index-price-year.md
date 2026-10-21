<!-- topic:数据库参考|MySQL index_price_year -->
<!-- summary:同花顺指数日线年度完整集合证明，与日线事实同事务确认。 -->
<!-- group:MySQL -->
# MySQL index_price_year

年度完整性计数与内容摘要包括来源负量额，量额异常不删除日期或阻断完整年度；用途质量由正式查询按所选日期另行标注。

## 用途与归属

量额质量由正式查询从有符号原值派生，不以非负SQL约束拒绝整年。已有库关闭程序、清空待归档后运行scripts/migrate_index_price_numeric_quality.py --apply显式移除旧约束，维护前后核对原业务内容，启动不迁移。

固定来源ths，采集项目ths-index-prices；统一归档器调用datasets/index_prices.py写入，data/index_prices.py提供查询。来源HTTP正文不保存。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `index_code` | `CHAR(6) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 同花顺来源指数六位编号，保持1A/1B等身份，不推导股票代码。 |
| `quote_year` | `SMALLINT UNSIGNED NOT NULL` | 完整来源年度身份，来源1990年起，不凭最大日期补造历史。 |
| `source_count` | `SMALLINT UNSIGNED NOT NULL` | last年份目录声明的当年有效收盘记录数量。 |
| `row_count` | `SMALLINT UNSIGNED NOT NULL` | 该年正式日行数量；不能单独证明完整，须结合内容摘要及来源集合。 |
| `first_date` | `DATE NOT NULL` | 该年已存首个真实来源日期。 |
| `last_date` | `DATE NOT NULL` | 该年已存最后真实来源日期，不能代替完整年度证明。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 全年按日期排序的日期和六项数值规范内容SHA256。 |
| `complete` | `BOOLEAN NOT NULL` | 该年度来源集合是否有完整响应证明且与存储内容一致，部分窗口不冒充完整；来源缺少开盘/最高/最低价可为NULL，完整表示来源日期集合及必需收盘量额齐全，不承诺四价齐全。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 该年度证明最近实际变化的观察代次，北京时间微秒；同内容不刷新，SQL确认版本在统一状态。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (index_code, quote_year)`
- `CONSTRAINT ck_index_year_code CHECK (REGEXP_LIKE(index_code, '^[0-9A-Z]{6}$'))`
- `CONSTRAINT ck_index_year_count CHECK (source_count BETWEEN 1 AND 366 AND row_count BETWEEN 1 AND 366)`
- `CONSTRAINT ck_index_year_dates CHECK (YEAR(first_date) = quote_year AND YEAR(last_date) = quote_year AND first_date <= last_date)`
- `CONSTRAINT ck_index_year_hash CHECK (REGEXP_LIKE(content_hash, '^[0-9a-f]{64}$'))`
- `CONSTRAINT ck_index_year_complete CHECK (complete IN (0,1) AND (complete = 0 OR source_count = row_count))`

成交额NULL参与内容摘要，来源补值沿原修订/防覆盖规则更新；complete不代表成交额齐全。complete仅表示来源年度日期集合及内容完整；价格质量由日行四价关系独立派生，异常原值仍计入摘要，质量项不通过不能伪装年度缺日。

## 读写与关联

年度完整证明继续供准备检查，范围图已读取行数不替代年度内容证明；图表读取不更新观察版本。

日行由(index_code,trade_date)唯一；年度头由(index_code,quote_year)唯一，与实际日期集合及内容摘要绑定。单指数使用主键，跨指数日期页使用ix_index_price_date。查询页200、最多500，年度最多366行；不外键级联到当前stock_index，目录移除不删除历史。完整年与近期窗口使用同一正式写入器，同年一个摘要身份，模式和来源计数参与内容。观察代次仅防迟到覆盖，不是源站修订版本。

## 保留与恢复

MySQL持久保留历史；相同内容不执行业务DML，有效修订只写变化日期及受影响证明。统一归档成功即删待归档消息，失败保留重放；Redis丢失从SQL年度证明重新补缺，近期窗口重读。手工改SQL须停止归档并失效该来源摘要及年度证明，不清空共享Redis。

## 维护与相关说明

scripts/create_index_price_schema.py是显式新增入口，关闭Empire、待归档0并取得维护锁，前后核对原有表数量、结构和统一状态；启动不改表，新空库init-db。普通采集不执行DDL。

[同花顺指数历史日行情](help:同花顺指数历史日行情)、[MySQL collection_state](help:MySQL%20collection_state)
