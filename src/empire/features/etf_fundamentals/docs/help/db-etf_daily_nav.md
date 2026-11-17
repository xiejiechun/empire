<!-- topic:数据库参考|MySQL etf_daily_nav -->
<!-- summary:ETF来源事实或内容绑定覆盖证明；明确身份、精确字段、版本与恢复边界。 -->
<!-- group:MySQL -->
# MySQL etf_daily_nav

## 用途与归属

etf_fundamentals业务拥有；两所份额按来源共表，净值固定天天基金ttjj。证明表不是运行日志，项目状态只在collection_state。

## 结构与身份

| 字段 | SQL 声明 | 含义 |
| --- | --- | --- |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | ETF统一代码，六位代码加.SH或.SZ；不级联当前目录。 |
| `nav_date` | `DATE NOT NULL` | 来源净值/收益披露日期，可为非交易日。 |
| `value_kind` | `VARCHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | nav是真正单位净值；income为收益展示口径。 |
| `unit_nav` | `DECIMAL(28,10) NULL` | DWJZ真正单位净值；收益口径或源端空白NULL。 |
| `accumulated_nav` | `DECIMAL(28,10) NULL` | LJJZ累计净值；收益口径或源端空白NULL。 |
| `daily_change_pct` | `DECIMAL(28,10) NULL` | JZZZL来源增长率百分数值，保留来源精度。 |
| `income_value` | `DECIMAL(28,10) NULL` | 收益展示口径DWJZ；不作为单位净值。 |
| `income_basis_shares` | `DECIMAL(28,10) NULL` | 有历史对应日期依据的收益基数；未核实NULL，不猜100或10000。 |
| `yield_7d_pct` | `DECIMAL(28,10) NULL` | 收益展示口径LJJZ七日年化百分数值。 |
| `currency` | `CHAR(3) CHARACTER SET ascii COLLATE ascii_bin NULL` | 已证实ISO币种；当前来源未核实，NULL，不默认CNY。 |
| `purchase_status` | `VARCHAR(64) NULL` | SGZT申购状态，源端文本。 |
| `redemption_status` | `VARCHAR(64) NULL` | SHZT赎回状态，源端文本。 |
| `distribution_text` | `VARCHAR(1024) NULL` | FHSP完整分红送配说明，空白NULL，超长拒绝截断。 |
| `fund_type` | `VARCHAR(16) NULL` | 来源FundType，和NAVTYPE独立。 |
| `income_label` | `VARCHAR(64) NULL` | 来源当前SYType标签，不能倒推全部历史基数。 |
| `nav_type` | `VARCHAR(16) NULL` | 来源NAVTYPE原始标记，不代表净值/收益分类。 |
| `income_start_date` | `DATE NULL` | 来源SDATE收益起点；未知NULL。 |
| `actual_income` | `DECIMAL(28,10) NULL` | 来源ACTUALSYI可选收益字段，未提供NULL。 |
| `dividend_value` | `DECIMAL(28,10) NULL` | 来源FHFCZ可选分红数值。 |
| `dividend_per_ten` | `DECIMAL(28,10) NULL` | 来源FHFCZ10可选分红数值，保留来源标记语义。 |
| `dividend_basis` | `VARCHAR(64) NULL` | 来源FHFCBZ可选分红标记，不据此自动生成折算事件。 |
| `distribution_type` | `VARCHAR(64) NULL` | 来源DTYPE可选标记。 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 有效变更版本观测北京时间；相同内容不为刷新时间写库。 |

- `PRIMARY KEY (unified_code,nav_date)`
- `KEY ix_etf_nav_date (nav_date,unified_code)`
- `CONSTRAINT ck_etf_nav_code CHECK (unified_code REGEXP '^[0-9]{6}[.](SH|SZ)$')`
- `CONSTRAINT ck_etf_nav_kind CHECK ((value_kind='nav' AND income_value IS NULL AND income_basis_shares IS NULL AND yield_7d_pct IS NULL) OR (value_kind='income' AND unit_nav IS NULL AND accumulated_nav IS NULL))`
- `CONSTRAINT ck_etf_nav_values CHECK ((unit_nav IS NULL OR unit_nav>=0) AND (accumulated_nav IS NULL OR accumulated_nav>=0) AND (income_basis_shares IS NULL OR income_basis_shares>0))`
- `CONSTRAINT ck_etf_nav_income_date CHECK (income_start_date IS NULL OR income_start_date<=nav_date)`

## 读写与关联

采集通过Redis统一归档在事务中修改事实、完整单元键/内容摘要及项目状态。任务内只读预览和复盘使用正式SQL，证券范围走主键、跨证券日查询走日期索引；每页默认200、最多500。没有对当前目录的级联删除。

## 保留与恢复

历史保留；相同内容零业务DML，迟到旧版本不覆盖。净值范围版本段含源端缺日期，阻止旧响应复活已撤回行。Redis摘要失效回SQL，提交后重放安全；运行记录和原始错误不入本表。

## 维护与相关说明

新空库由schema.sql，旧库经显式create_etf_fundamentals_schema.py持锁建表；停机、清队、前后业务核对，启动不迁移。来源/必需字段变化须显式失效相关覆盖及摘要。参考[ETF份额与净值](help:ETF份额与净值)。
