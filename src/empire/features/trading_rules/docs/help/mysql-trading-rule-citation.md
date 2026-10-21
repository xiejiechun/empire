<!-- topic:数据库参考|MySQL trading_rule_citation -->
<!-- summary:交易规则的结构化共享必要条款引用，避免重复保存整份文档。 -->
<!-- group:MySQL -->
# MySQL trading_rule_citation

## 用途与归属

固定归属reviewed_rules，七项独立任务共用features/trading_rules/dataset.py正式归档及features/trading_rules/query.py有界查询；页面不写SQL。规则值、引用和状态保持同事务，结构及稳定身份不变。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `citation_key` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 关联引用条款的SHA256身份。 |
| `issuer` | `VARCHAR(100) NOT NULL` | 实际发布或转述机构，新华社转载不冒充结算机构。 |
| `title` | `VARCHAR(200) NOT NULL` | 文档正式标题。 |
| `source_url` | `VARCHAR(1000) NOT NULL` | 已核实来源正文或附件地址。 |
| `published_date` | `DATE NOT NULL` | 文件公布日期，非采集时刻。 |
| `document_hash` | `CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL` | 本次核实正文SHA256摘要，不保存全文。 |
| `clause_key` | `VARCHAR(100) NOT NULL` | 正式条款编号或已声明公告条款名称。 |
| `excerpt` | `VARCHAR(4000) NOT NULL` | 不超过4000字的必要条文原文，不保存整份业务文档。 |

### 主键、索引与约束

- `PRIMARY KEY (citation_key)`

## 读写与关联

参数引用同事务写入，与collection_state一项一行证明绑定；摘要包含规范参数及全部必要引用，日期与关键字段结构化，不整份JSON入库。普通浏览每页200行，准备扫描1001行，超过当前1000行契约拒绝完整；条文按需读取。引用按文档和条款复用，修订后仅删除已无参数引用的旧条款，相同内容无业务DML，热摘要免SQL，迟到旧消息不覆盖。

## 保留与恢复

保留已审核历史生效段，不把当前规则套用历史；未知结束日期和最低费用保持未知。成功插入、更新、相同或旧版确认都由统一归档器清理对应Redis业务消息。SQL失败或提交后确认失败保留重放，Redis丢失从官方文件重新核验，不承诺恢复内存队列。当前引用不是完整法规库。

## 维护与相关说明

正常关闭程序，待归档队列为0，通过scripts/create_rule_schema.py显式增量建两表；沿用公共维护锁、库存数量及状态摘要核对，启动不迁移。语义或必需字段变化须审核并重建受影响证明；不通过降低数据准备要求使未知规则通过。容量及当前范围见docs/trading-rules.md。

[交易规则与税费](help:交易规则与税费)
