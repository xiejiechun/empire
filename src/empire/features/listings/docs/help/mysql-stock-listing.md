<!-- topic:数据库参考|MySQL stock_listing -->
<!-- summary:同花顺首次上市与发行资料，一证券一行。 -->
<!-- group:MySQL -->
# MySQL stock_listing

## 用途与归属

同花顺首次上市与发行资料，一证券一行。

统一归档器调用 `datasets/listings.py` 写入；`data/listings.py` 提供正式查询。业务页面不直接写表。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 统一证券代码（六位代码.SH/.SZ/.BJ）；不能只按裸代码关联市场。 |
| `listing_date` | `DATE NOT NULL` | 来源首次上市日期；行情头中为确定采集起点的关联日期。 |
| `establish_date` | `DATE NULL` | 来源成立日期，可为空；与上市日期冲突时保留原值并提示。 |
| `issuance_num` | `DECIMAL(24,4) NULL` | 规范发行股数（股），来源缺值为 NULL。 |
| `issuance_price` | `DECIMAL(24,4) NULL` | 发行价格（元/股），来源缺值为 NULL。 |
| `first_day_open_price` | `DECIMAL(24,4) NULL` | 首日开盘价（元/股）。 |
| `estimated_raised` | `DECIMAL(24,4) NULL` | 预计募资金额（元）。 |
| `actual_raised` | `DECIMAL(24,4) NULL` | 实际募资金额（元）。 |
| `issuance_pe` | `DECIMAL(20,4) NULL` | 发行市盈率，保留来源值，不自行以其他价格计算。 |
| `winning_rate` | `DECIMAL(20,10) NULL` | 中签率百分数，范围 0～100，不是 0～1 比例。 |
| `lead_underwriter` | `VARCHAR(2048) NULL` | 主承销商文字，来源缺值为 NULL。 |
| `sponsor` | `VARCHAR(2048) NULL` | 保荐人文字，来源缺值为 NULL。 |
| `history` | `MEDIUMTEXT NULL` | 完整历史沿革文字，最多 256 KiB，不静默截断。 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 规范业务内容 SHA-256；不包含批次、页号和纯观测时间。 |
| `contract_version` | `SMALLINT UNSIGNED NOT NULL` | 上市资料契约，当前 2；数据库约束允许 1/2 以支持显式升级，旧证明不能替代契约 2 验收。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前入库存储版本的请求观测时刻（北京时间），用于版本排序；相同内容不刷新。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (unified_code)`
- `KEY ix_listing_date (listing_date, unified_code)`
- `CONSTRAINT ck_listing_dates CHECK (listing_date >= '1900-01-01' AND (establish_date IS NULL OR establish_date >= '1900-01-01'))`
- `CONSTRAINT ck_listing_numbers CHECK ((issuance_num IS NULL OR issuance_num >= 0) AND (issuance_price IS NULL OR issuance_price >= 0) AND (first_day_open_price IS NULL OR first_day_open_price >= 0) AND (estimated_raised IS NULL OR estimated_raised >= 0) AND (actual_raised IS NULL OR actual_raised >= 0) AND (winning_rate IS NULL OR winning_rate BETWEEN 0 AND 100))`
- `CONSTRAINT ck_listing_history CHECK (history IS NULL OR OCTET_LENGTH(history) <= 262144)`
- `CONSTRAINT ck_listing_contract CHECK (contract_version IN (1, 2))`

## 读写与关联

档案查询接受完整统一证券身份，保留市场精确匹配；沿革独立按需读取，不截断正文。

unified_code 点查一行、listing_date/unified_code 游标列表（最多 200 行）；列表不加载 history 正文，覆盖检查以当前股票池 LEFT JOIN 摘要/日期/契约，资料不依赖 stock 的外键。

缺必需上市日时只归档 collection_state 不完整状态，保留旧有效资料；日期冲突保留原值。

## 保留与恢复

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/create_listing_schema.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[上市与发行资料](help:上市与发行资料)、[数据库职责与查阅](help:数据库职责与查阅)、[MySQL collection_state](help:MySQL%20collection_state)
