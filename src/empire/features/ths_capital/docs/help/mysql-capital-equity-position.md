<!-- topic:数据库参考|MySQL capital_equity_position -->
<!-- group:MySQL -->
<!-- summary:同花顺资本运作的结构化来源事实；核心字段可SQL查询，重复零业务写入，来源未列示历史保留。 -->
# MySQL capital_equity_position

## 用途与归属
固定来源ths，数据集ths.capital.security，项目ths-capital，唯一正式查询ths_capital.query，统一归档写入。

## 结构与身份
| 字段 | 类型 | 含义 |
| --- | --- | --- |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 记录键；以来源实际精度保存 |
| `unified_code` | `VARCHAR(9) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 股票；以来源实际精度保存 |
| `section` | `VARCHAR(20) NOT NULL` | 栏目；以来源实际精度保存 |
| `event_date` | `DATE NULL` | 公告日/报告期；以来源实际精度保存 |
| `category` | `VARCHAR(100) NULL` | 分类；以来源实际精度保存 |
| `target` | `VARCHAR(1000) NULL` | 所持对象；来源未公布/空值为NULL，保留完整持仓，不跨期猜填 |
| `investment_type` | `VARCHAR(200) NULL` | 投资类型；以来源实际精度保存 |
| `quantity` | `DECIMAL(28,6) NULL` | 持股数量(股)；金额元/数量股/比例百分数，NULL未知，无汇率换算 |
| `quantity_estimated` | `BOOLEAN NOT NULL` | 数量为估算；以来源实际精度保存 |
| `ratio` | `DECIMAL(28,6) NULL` | 持股比例；金额元/数量股/比例百分数，NULL未知，无汇率换算 |
| `profit` | `DECIMAL(28,6) NULL` | 综合盈亏(元)；金额元/数量股/比例百分数，NULL未知，无汇率换算 |
| `in_window` | `BOOLEAN NOT NULL` | 当前完整来源响应仍列示；只在窗口成员变化时修改，不代表业务仍有效；以来源实际精度保存 |
| `content_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 本条规范事实SHA-256，不含运行批次/页/观测时间；以来源实际精度保存 |
| `version_observed_at` | `DATETIME(6) NOT NULL` | 当前存储内容的观测版本，北京时间；不是来源修订号；以来源实际精度保存 |

## 读写与关联

正式约束：

- `PRIMARY KEY (record_key)`
- `KEY idx_equity_position_date (section,event_date,unified_code,record_key)`
- `KEY idx_equity_position_security (section,unified_code,event_date,record_key)`
- `KEY idx_equity_position_window (unified_code,in_window,record_key)`
- `CONSTRAINT ck_equity_position_window CHECK (in_window IN (0,1))`
- `CONSTRAINT ck_equity_position_section CHECK (section IN ('invest'))`

主键`record_key`为证券/栏目/公告日或报告期/业务锚点+重复次序的SHA-256；源顺序不冒充稳定编号。 `idx_equity_position_date (section,event_date,unified_code,record_key)`。 `idx_equity_position_security (section,unified_code,event_date,record_key)`。 `idx_equity_position_window (unified_code,in_window,record_key)`。 列表按栏目和日期游标最多100条，不读取完整说明正文；详情按主键，原事件最多关联1000条解除；窗口审计按证券索引，不扫描历史正文。

## 保留与恢复

数值负零统一为0，以保证SQL往返及重复内容比较稳定；不把未知金额填成零。
来源窗口外保留历史，不自动删除；解除通过parent_key关联原质押/冻结，不按预计截止日推断实际解除。无变化不做业务DML，SQL状态同事务，旧观测不能覆盖新内容。只有in_window变化是真实窗口成员修订。Redis可信摘要免SQL，确认成功由统一归档器清队，出错留队。

## 维护与相关说明
显式scripts/create_ths_capital_schema.py建表，启动不DDL。结构/契约变化须显式重建覆盖和摘要；手工改业务须停归档并失效ths_capital来源摘要。参见[业务使用说明](help:同花顺公司资本运作)。
