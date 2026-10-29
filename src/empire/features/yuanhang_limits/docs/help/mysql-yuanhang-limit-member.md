<!-- topic:数据库参考|MySQL yuanhang_limit_member -->
<!-- summary:远航涨跌停分析结构化业务表，固定来源ths_yuanhang。 -->
<!-- group:MySQL -->
# MySQL yuanhang_limit_member

## 用途与归属

五个日期池共享池头和成员，原因由独立证券日任务负责。固定来源ths_yuanhang；完整日期池或证券日原因是归档单元。不是运行日志，不与当前股票名单建立删除级联。

## 结构与身份

| 字段 | SQL声明 | 含义 |
| --- | --- | --- |
| `trade_date` | `DATE NOT NULL` | 来源查询交易日期，不从采集时刻推断。 |
| `pool_type` | `VARCHAR(24) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 五池来源策略标识。 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 六位代码和SH/SZ后缀；不随当前股票名单裁剪。 |
| `source_market_id` | `SMALLINT UNSIGNED NULL` | 原市场编号；明确NULL原样保留。 |
| `identity_basis` | `VARCHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | market_id或source_board，记录身份判定依据。 |
| `change_rate` | `DECIMAL(48,24) NULL` | 涨跌幅，百分点。 |
| `latest` | `DECIMAL(48,24) NULL` | 价格，元。 |
| `turnover_rate` | `DECIMAL(48,24) NULL` | 换手率，百分点。 |
| `currency_value` | `DECIMAL(48,24) NULL` | 流通市值，元。 |
| `sum_market_value` | `DECIMAL(48,24) NULL` | 总市值，元。 |
| `rise_rate` | `DECIMAL(48,24) NULL` | 来源涨速，时间窗口尚未完全核实。 |
| `turnover` | `DECIMAL(48,24) NULL` | 成交额，元。 |
| `order_amount` | `DECIMAL(48,24) NULL` | 封单额，元。 |
| `order_volume` | `DECIMAL(48,24) NULL` | 来源封单量，完整单位证据尚未冻结。 |
| `limit_up_suc_rate` | `DECIMAL(48,24) NULL` | 成功率，0～1比例。 |
| `open_num` | `INT UNSIGNED NULL` | 开板次数，非负整数或NULL。 |
| `high_days_value` | `INT UNSIGNED NULL` | 来源整数标记，不推测解码。 |
| `is_new` | `INT UNSIGNED NULL` | 新股标记0/1/NULL。 |
| `is_again_limit` | `INT UNSIGNED NULL` | 回封标记0/1/NULL。 |
| `name` | `VARCHAR(80) NOT NULL` | 来源证券名称。 |
| `market_type` | `VARCHAR(32) NOT NULL` | 原板块类型。 |
| `reason_type` | `TEXT NULL` | 原原因摘要，最多4096字符。 |
| `limit_up_type` | `VARCHAR(128) NULL` | 原涨停状态文本。 |
| `limit_down_type` | `VARCHAR(128) NULL` | 原跌停状态文本。 |
| `high_days` | `VARCHAR(80) NULL` | 原N天M板文本。 |
| `change_tag` | `VARCHAR(80) NULL` | 原状态标记。 |
| `top_concept` | `VARCHAR(1024) NULL` | 来源941948930概念字段，允许NULL。 |
| `first_limit_up_time` | `DATETIME NULL` | 来源Unix秒转北京时间，必须属于查询日，未知为NULL。 |
| `last_limit_up_time` | `DATETIME NULL` | 来源Unix秒转北京时间，必须属于查询日，未知为NULL。 |
| `first_limit_down_time` | `DATETIME NULL` | 来源Unix秒转北京时间，必须属于查询日，未知为NULL。 |
| `last_limit_down_time` | `DATETIME NULL` | 来源Unix秒转北京时间，必须属于查询日，未知为NULL。 |

## 主键、索引与约束

- `PRIMARY KEY (trade_date,pool_type,unified_code)`
- `KEY idx_yuanhang_limit_member_security (unified_code,trade_date,pool_type)`
- `KEY ix_yuanhang_member_date_code (trade_date,unified_code)`
- `CONSTRAINT ck_yuanhang_limit_member_probability CHECK (limit_up_suc_rate IS NULL OR limit_up_suc_rate BETWEEN 0 AND 1)`

## 读写与关联

日终归档拒绝未来日期，以及观察于查询当日北京时间15:30前的消息；盘中五池变化快照只存独立Redis键，不进入本表。收盘后重新请求并核验最终池，再由原统一归档路径写入；字段、唯一键和旧版本防覆盖规则不变。

统一归档器是唯一写入路径。池头与成员、状态同事务提交；修订仅改实际变化，重复内容零业务DML，较早观察版本不能覆盖更新核验。成功即清理对应Redis待归档消息，失败保留。SQL提交后重放不重复写业务。

日池列表最多200条、证券历史最多500条，按稳定业务键翻页；原因按证券日点查。数值保留DECIMAL(48,24)，超精度失败，不舍入。NULL与零不同，来源空池与未采集不同。

## 保留与恢复

已归档历史长期保留，不随证券退出当前股票名单删除。Redis丢失从SQL覆盖恢复，未归档单元须补采；来源空池不推定历史边界。

## 维护与相关说明

显式维护入口scripts/create_yuanhang_limits_schema.py，先正常停机、核实队列及旧数据，再新增三表并校验。启动仅检查结构，不自动迁移；维护业务内容前须停止归档并失效相应摘要和完成证明。

操作与日期语义见[远航版涨跌停分析](help:远航版涨跌停分析)。

来源时间0作为哨兵保存在北京时间1970-01-01 08:00:00，界面显示未知（来源0）；非零时刻必须属于池日期。identity_basis除market_id/source_board外，pool_history表示复用已归档明确身份，sina_lookup表示缺失身份经共享精确证券查询核实，原source_market_id的NULL不改写。

市场复盘只读本表的日期范围数据，用于日历、涨跌停统计或题材轮动；不增加业务写入或缓存副本。参见[市场复盘](help:市场复盘)。
