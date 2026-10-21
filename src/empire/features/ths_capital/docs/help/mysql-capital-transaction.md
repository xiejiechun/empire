<!-- topic:数据库参考|MySQL capital_transaction -->
<!-- group:MySQL -->
<!-- summary:同花顺资本运作的结构化来源事实；核心字段可SQL查询，重复零业务写入，来源未列示历史保留。 -->
# MySQL capital_transaction

## 用途与归属
固定来源ths，数据集ths.capital.security，项目ths-capital，唯一正式查询ths_capital.query，统一归档写入。

## 结构与身份
| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 记录键；以来源实际精度保存 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 股票；以来源实际精度保存 |
| `section` | `VARCHAR(20) NOT NULL` | 栏目；以来源实际精度保存 |
| `event_date` | `DATE NULL` | 公告日/报告期；以来源实际精度保存 |
| `target` | `TEXT NULL` | 交易标的；以来源实际精度保存 |
| `buyer` | `TEXT NULL` | 买方/受让方；以来源实际精度保存 |
| `seller` | `TEXT NULL` | 卖方/出让方；以来源实际精度保存 |
| `counterparty` | `TEXT NULL` | 交易方；以来源实际精度保存 |
| `amount` | `DECIMAL(28,6) NULL` | 交易金额；金额元/数量股/比例百分数，NULL未知，无汇率换算 |
| `currency` | `VARCHAR(40) NULL` | 金额币种；以来源实际精度保存 |
| `status` | `VARCHAR(100) NULL` | 交易进度；以来源实际精度保存 |
| `transfer_ratio` | `DECIMAL(28,6) NULL` | 转让比例；金额元/数量股/比例百分数，NULL未知，无汇率换算 |
| `payment` | `VARCHAR(200) NULL` | 支付方式；以来源实际精度保存 |
| `method` | `TEXT NULL` | 交易方式；以来源实际精度保存 |
| `relationship` | `TEXT NULL` | 关联关系；以来源实际精度保存 |
| `description` | `TEXT NULL` | 交易概述/简介；以来源实际精度保存 |
| `impact` | `TEXT NULL` | 交易影响；以来源实际精度保存 |
| `in_window` | `BOOLEAN NOT NULL` | 当前完整来源响应仍列示；只在窗口成员变化时修改，不代表业务仍有效；以来源实际精度保存 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 本条规范事实SHA-256，不含运行批次/页/观测时间；以来源实际精度保存 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储内容的观测版本，北京时间；不是来源修订号；以来源实际精度保存 |

## 读写与关联

正式约束：

- `PRIMARY KEY (record_key)`
- `KEY idx_transaction_date (section,event_date,unified_code,record_key)`
- `KEY idx_transaction_security (section,unified_code,event_date,record_key)`
- `KEY idx_transaction_window (unified_code,in_window,record_key)`
- `CONSTRAINT ck_transaction_window CHECK (in_window IN (0,1))`
- `CONSTRAINT ck_transaction_section CHECK (section IN ('asset','transfer','connect'))`

主键`record_key`为证券/栏目/公告日或报告期/业务锚点+重复次序的SHA-256；源顺序不冒充稳定编号。 `idx_transaction_date (section,event_date,unified_code,record_key)`。 `idx_transaction_security (section,unified_code,event_date,record_key)`。 `idx_transaction_window (unified_code,in_window,record_key)`。 列表按栏目和日期游标最多100条，不读取完整说明正文；详情按主键，原事件最多关联1000条解除；窗口审计按证券索引，不扫描历史正文。

## 保留与恢复

数值负零统一为0，以保证SQL往返及重复内容比较稳定；不把未知金额填成零。
来源窗口外保留历史，不自动删除；解除通过parent_key关联原质押/冻结，不按预计截止日推断实际解除。无变化不做业务DML，SQL状态同事务，旧观测不能覆盖新内容。只有in_window变化是真实窗口成员修订。Redis可信摘要免SQL，确认成功由统一归档器清队，出错留队。

## 维护与相关说明
显式scripts/create_ths_capital_schema.py建表，启动不DDL。结构/契约变化须显式重建覆盖和摘要；手工改业务须停归档并失效ths_capital来源摘要。参见[业务使用说明](help:同花顺公司资本运作)。
