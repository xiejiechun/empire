<!-- topic:数据库参考|MySQL trading_rule_value -->
<!-- summary:交易规则的结构化数值、时段及历史生效段，七项共用正式写入路径。 -->
<!-- group:MySQL -->
# MySQL trading_rule_value

## 用途与归属

固定归属reviewed_rules，七项独立任务共用features/trading_rules/dataset.py正式归档及features/trading_rules/query.py有界查询；页面不写SQL。规则值、引用和状态保持同事务，结构及稳定身份不变。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `record_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 种类、市场、板块、条件、参数及生效日的规范身份。 |
| `kind` | `VARCHAR(30) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 七项准备项目之一。 |
| `market` | `VARCHAR(2) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | SH、SZ、BJ或全国CN。 |
| `board` | `VARCHAR(10) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | MAIN、STAR、CHINEXT或ALL。 |
| `condition_key` | `VARCHAR(50) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 普通、豁免或来源未明确最低费用等已审核条件。 |
| `parameter_key` | `VARCHAR(50) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 按种类登记的数值、时段或说明参数。 |
| `effective_start` | `DATE NOT NULL` | 官方明确规则生效日期。 |
| `effective_end` | `DATE NULL` | 来源明确结束日；NULL为尚未知。 |
| `number_value` | `DECIMAL(16,8) NULL` | 精确数值；NULL为文本或时段参数，未知不填零。 |
| `text_value` | `VARCHAR(200) NOT NULL` | 不超过200字的具体解释及限制。 |
| `start_time` | `TIME NULL` | 北京时间时段起点；非时段为NULL。 |
| `end_time` | `TIME NULL` | 北京时间时段终点；非时段为NULL。 |
| `unit` | `VARCHAR(20) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | ratio、shares、CNY、Asia/Shanghai或text。 |
| `citation_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 关联引用条款的SHA256身份。 |

### 主键、索引与约束

- `PRIMARY KEY (record_key)`
- `KEY ix_rule_kind_market (kind,market,record_key)`
- `KEY ix_rule_citation (citation_key)`
- `KEY ix_rule_effective (kind,effective_start,record_key)`
- `CONSTRAINT fk_rule_citation FOREIGN KEY (citation_key) REFERENCES trading_rule_citation(citation_key)`
- `CONSTRAINT ck_rule_dates CHECK (effective_end IS NULL OR effective_end >= effective_start)`
- `CONSTRAINT ck_rule_number CHECK (number_value IS NULL OR number_value >= 0)`
- `CONSTRAINT ck_rule_session CHECK ((start_time IS NULL AND end_time IS NULL) OR (start_time IS NOT NULL AND end_time IS NOT NULL AND start_time < end_time))`

## 读写与关联

参数引用同事务写入，与collection_state一项一行证明绑定；摘要包含规范参数及全部必要引用，日期与关键字段结构化，不整份JSON入库。普通浏览每页200行，准备扫描1001行，超过当前1000行契约拒绝完整；条文按需读取。引用按文档和条款复用，修订后仅删除已无参数引用的旧条款，相同内容无业务DML，热摘要免SQL，迟到旧消息不覆盖。

## 保留与恢复

保留已审核历史生效段，不把当前规则套用历史；未知结束日期和最低费用保持未知。成功插入、更新、相同或旧版确认都由统一归档器清理对应Redis业务消息。SQL失败或提交后确认失败保留重放，Redis丢失从官方文件重新核验，不承诺恢复内存队列。当前引用不是完整法规库。

## 维护与相关说明

正常关闭程序，待归档队列为0，通过scripts/create_rule_schema.py显式增量建两表；沿用公共维护锁、库存数量及状态摘要核对，启动不迁移。语义或必需字段变化须审核并重建受影响证明；不通过降低数据准备要求使未知规则通过。容量及当前范围见docs/trading-rules.md。

[交易规则与税费](help:交易规则与税费)
