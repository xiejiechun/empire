<!-- topic:数据库参考|MySQL collection_state -->
<!-- summary:统一 SQL 已确认采集状态，每 namespace/project_id 一行。 -->
<!-- group:MySQL -->
# MySQL collection_state

## 用途与归属

统一 SQL 已确认采集状态，每 namespace/project_id 一行。

统一归档器通过 `infra/collection_state.py` 和 `collection_state_unit.py` 与业务写入同事务提交；采集恢复、数据准备及查询读取当前项目确认。

按项目诊断通过 `diagnostics/project.py` 只读指定 namespace/project_id 的 progress、coverage、契约版本及更新时间；每个 JSON 投影最多 128 KiB，超限明确标记截断，不读取完整 units 正文，不更新确认时间。

## 结构与身份

| 字段 | SQL 声明（类型、空值及默认值） | 业务含义 |
| --- | --- | --- |
| `namespace` | `VARCHAR(160) NOT NULL` | 配置/采集空间，取 redis.namespace；与业务来源不同。 |
| `project_id` | `VARCHAR(100) NOT NULL` | 已登记的采集项目 ID，每项目只保留一条状态。 |
| `source` | `VARCHAR(80) NOT NULL` | 来源标识；新闻逐行保留，项目状态与登记来源一致。 |
| `dataset` | `VARCHAR(80) NOT NULL` | 当前状态对应的数据集/归档契约标识。 |
| `payload` | `JSON NOT NULL` | 规范状态 JSON：progress 页/批次确认，publication 最后实际发布，coverage/observed 范围及月份确认，units/manifest 按数据集保存集合与版本；不存成功响应或运行历史。 |
| `updated_at` | `DATETIME(6) NOT NULL` | 该行最近实际内容更新时刻，MySQL DATETIME 按北京时间保存。 |

### 主键、索引与完整性约束

- `PRIMARY KEY (namespace, project_id)`

## 读写与关联

每日复盘仅只读当前配置namespace及project_id=ths-industries、source=ths的行业证明，复用公开行业校验核对contract_version、industry_count、member_count、digest及observed_at与当前目录/成员一致。证明缺失、错误或版本异常只使板块汇总未知，不读取其他namespace替代，也不更新状态或确认时间。归档证明只核验当前行业集合，不能证明其成员在所选日有资金记录；无交集时板块仍未知。

股票 publication 与 stock 同事务；日历 observed 按月；单位型数据只读写当前 unit 并保留其他单位。progress 最高页不是整轮成功证明，必须确认本轮 Stream 无剩余业务消息。

与业务事务提交，只记录最近 SQL 回源确认；Redis 摘要命中不读写本表。不是逐轮运行记录，也不恢复之后的无变化核验上界或未归档断点。

远航日线每证券单位以 `price_ranges` 保存每年不重叠日期版本段（含区间内无成交的自然日），以 `full_checked` 保存完整历史的 SQL 核验下界。日常恢复只读年度证明和所选证券状态，补缺及近期回看不扫描全部日线正文。较早的不相交区间可以补入，但不能使年度证明时间及原生市场退回旧版本。旧年度状态必须在关闭程序、待归档为零后通过 `scripts/migrate_yuanhang_ranges.py` 显式转换；该入口备份原状态并核对行情数量与年度证明摘要，不改业务事实和表结构。

远航指数组件每项目一行状态，局部单位键为严格六位指数编号（含1A0001），与股票统一代码分开验证。目录保存当前集合hash/count；网页成分按指数保存available/count/hash与核验版本；日K按指数保存native_market、history_start、price_ranges和full_years。恢复须与年度SQL头匹配，近期区间不能作为全历史完成；删除旧四表时仅显式清除旧两个项目状态。

同花顺持有人单位证明的source_gaps为最多100条来源身份缺口（kind、report_date、source_panel、reason）；定位不作为债券身份，未知债券正文不入库。债券栏目availability=source_gap，其他栏目可独立完整。消息schema5绑定缺口摘要，来源补齐后重新采集更新证明。

东方财富回购coverage使用count（方案数）、digest（规范SQL集合滚动SHA-256）、observed_at（该证明的带时区确认时刻）及contract。contract=1为完整来源核验；contract=2为完整基线加近期增量归档后的组合证明，额外保存full_observed_at（最近完整来源核验的带时区时刻），不因近期更新延长完整核验时效。字段均有界，无逐轮历史；完整核验最多间隔三天，缺失或过期回完整采集。增量业务全部归档清队后才发布组合证明，证明仍由统一归档确认；旧完整证明/在途消息保留原语义，无DDL或启动迁移。

同花顺三表证券证明增加可选fingerprint_hash（64字符SHA-256），资本运作增加fingerprint_hash及content_digest（完整规范rows与availability的SHA-256）；均同业务确认后写入。维护规划只投影observed_at、digest/content_digest、数量及fingerprint_hash，可信Redis摘要须与SQL内容hash匹配才补充确认时间。资本运作旧证明缺content_digest时保守回查，待正常SQL回源后补充；旧热摘要在有效期内仍可能免SQL，不能据此伪造新字段。全池manifest是组合范围证明，财报时效改为逐证券SQL/可信摘要最早确认时间，不以重新组合时间冒充全部更新。

## 保留与恢复

通达信财报解读六项和个股解禁的units证明增加可选fingerprint_hash（64字符SHA-256），绑定该完整单元的规范归档内容；仅内容一致且版本有效的统一Redis摘要可补充核验时间，缺字段回SQL时间。旧季度/月最长90天、未变化户数最长30天回查，manifest的新时间不能延长旧单元时效。缺失证明立即补采，手工改业务须同步失效受影响单元证明。

通达信分红manifest扩展periods（报告日期到证明的映射，最多1000期），每期count为完整来源行数、digest为规范来源行SHA-256、observed_at为带时区实际核验时间；period_scope_hash为排序后报告日期集合的SHA-256，缺期或损坏不得当成完整。复用旧期不更新其时间。每轮最终清单通过原归档器提交这一个状态行，不把这些观测时间加入业务指纹；证券业务单元仍保留指纹快径和零重复业务DML。旧清单没有此扩展时下一轮保守完整核验一次，无DDL或启动迁移。

MySQL 持久保存，Redis 丢失不删除本表；未归档数据须按来源生命周期重采。成功、同内容及旧版本确认后统一清队，失败保留。手工修改业务前正常关闭归档并失效相关来源摘要，不直接清空 Redis。

## 维护与相关说明

结构与约束以 `sql/schema.sql` 为现行契约；新空库用 init-db，已有库只通过对应显式维护入口升级，启动不改表。先核对队列、业务数量/集合，维护后验证正式查询。

维护入口：`scripts/migrate_collection_state.py`（按该入口的预检与显式操作执行，不直接将历史维护当每次启动步骤）。

[采集进度与运行记录](help:采集进度与运行记录)、[数据库职责与查阅](help:数据库职责与查阅)


财报解读新增五项目：units局部键支持规范统一证券（如000001.SZ）和季度报告期|市场（如2026-06-30|SZ），严格验证日期/证券格式后JSON_SET；既有SZ:000001格式继续用于原声明项目。每响应完整集合摘要和数量、manifest整轮范围分别保存，同内容不更新业务表。每项目仍仅一行状态，无成功响应副本。

持有人每证券证明可选fingerprint_hash为64字符SHA-256，绑定该证券三栏及缺口的规范内容；维护规划仅在统一Redis指纹与此hash一致且版本有效时补充确认时间。旧证明缺此字段仍可正式审计，维护只使用SQL确认时间，不自动改写历史证明。planning.py只投影调度摘要，不读取整份历史正文，不替代正式数据准备审计。
