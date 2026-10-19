# 股东研究业务包

本目录拥有同花顺一个股东研究采集任务的三个栏目：前十大股东、前十大流通股东和十大债券持有人。运行时仍为一个采集插件、三个查询插件和三个 UI 插件；`bundle.py` 只登记现有贡献，保留与资本运作交错的原装配顺序。

## 唯一定位入口与边界

| 入口 | 公开能力及修改位置 |
| --- | --- |
| [contract.py](contract.py) | 报告/成员字段、`report_key`、`digest`、`number`/`quantity`、`validate`/`validate_gaps`及质量结果；跨模块读取本业务规则从这里开始，不反向引用采集器 |
| [query.py](query.py) | `HolderDataPlugin` 经 `{kind}.query` 提供 `securities`、`browse`、`detail`、`preparation_check`；页面只调能力，数据库读取使用既有 MySQL read 通道 |
| [audit.py](audit.py) | 栏目窗口证明、报告集合/正文、来源缺口与可选摘要时效的唯一审计实现；正式调用由 query 组织，不由 UI 另写 SQL 或另造证明 |
| [ui.py](ui.py) | `HolderUiPlugin` 为三栏各贡献一个按需页面，`HolderPage` 拥有查询、翻页与选择状态；不拥有下载或 SQL 写入 |
| [source.py](source.py) | 一次 `holder.html` 响应的三栏报告、成员、日期标签及来源缺口解析；仅负责持有人来源语义 |
| [collector.py](collector.py) | 当前池计划、有界预取、按序入队、连续断点和整轮末归档确认；不直接写 MySQL |
| [dataset.py](dataset.py) | `holders.reports` 的规范化、摘要/版本计划、三栏同事务业务写入和 collection_state 证明 |
| [bundle.py](bundle.py) | 本包唯一贡献登记；由 `features/builtin.py` 白名单收集，保持三查询、单采集、三页面及原稳定顺序，不复制 preparation 或页面元数据 |

包是代码归属，运行时仍按既有插件分别启停。`top_holders`、`float_holders`、`bond_holders` 三查询和三页面身份保持；三个页面关联同一个 `ths-holders` 任务，job 为 `ths-holders-v1`。数据集仍为 `holders.reports`、消息 schema 5、SQL 证明 contract 4、preparation cache_revision 4、摘要 namespace `ths_holders`。本包不增加第二组注册、下载器、队列或兼容入口。

公开契约的数值和质量返回有明确类型；`RawReport`、`RawGap` 是两个显式异构原始 JSON 边界，由运行时校验继续负责逐字段约束。类型注解不等于输入已被验证，也不代表全项目类型安全；类型检查结果以本批正式证据为准。

## 共享 HTML 的职责

公共 [sources/html.py](../../sources/html.py) 只拥有 `Document`/`Node` 节点树、文本与层级查找、HTML 标签闭合和嵌套表格边界。股东 `source.py` 与资本运作来源解析器共同使用同一个模块；它不解释股东字段、债券身份、资本事件或页面栏目，不注册可启停插件。公共行为变更同时回归两个消费者，不能让资本运作导入股东私有实现。

会话、代理、下载限额、站点频控、预取、统一入队、摘要及归档仍走现有公共路径。正常每证券必要 HTML 只请求一次，三栏共同解析；验证时的额外请求不固化成日常双读。

日常操作、来源生命周期和字段以 [同花顺前十大持有人说明](../../../../docs/ths-holders.md) 为权威正文。数据库参考见 [holder_report 与 holder_member](../../../../docs/database-reference.md)，迁移和实采准入见 [采集开发指南](../../../../docs/collector-development-guide.md)。目录迁移不修改正式表、消息版本、来源规则或用户已保存配置，不在启动时执行维护。

## 生命周期索引

下表对应现有实现；完整业务语义以来源说明为准，动态覆盖只记带日期证据。

| 阶段 | 正式行为与恢复边界 |
| --- | --- |
| 初始化 | 冻结当前股票池的统一代码有序集合；从首证券读取当前页面三栏全部可见报告期，不生成季度日期，不承诺上市以来完整历史 |
| 单元准入 | 三栏结构、字段和身份共同校验；结构性错误拒绝该证券。仅空名债券按报告隔离，来源缺口与可识别三栏一起入队；明确未提供栏目另记证明 |
| 入队与归档 | 校验后业务消息与断点原子入 Redis，继续下一证券；不逐证券等待归档。共享归档器独立消费，即时唤醒和60秒恢复扫描保持 |
| 完成 | 无缺口范围的最终 manifest 和本轮全部消息确认成功才完成。仅来源缺口时有效报告可全部归档，但保持 source_gap、首缺口断点及无完整 manifest |
| 后续与修订 | 每轮重新核验当前页面窗口，发现新增和窗口内修订；窗口外历史保留，较早独立修订不能靠当前页面发现 |
| 中断与补缺 | 从连续成功前缀之后恢复；失败证券后的有效证券继续处理，连续索引不越过首缺口。来源恢复后按原范围补采，不填零、补名或换证券证明完成 |
| Redis 丢失 | 从当前池首证券重核窗口，SQL历史保留；摘要缺失回 SQL 比较，不承诺恢复已丢失的内存断点或待归档消息 |
| 股票池变化/重新初始化 | 池摘要变化重建本轮计划；下载阶段重新初始化当前窗口，保留历史及已入队消息；awaiting_archive 阶段先确认原轮次 |
| 版本和清队 | 请求观察时刻限制迟到旧响应；相同业务零 DML，可信摘要免 SQL。插入、修订、相同或旧版确认成功均由统一归档器清队；SQL提交后的Redis失败保留消息安全重放 |
| 用户设置/启停 | 任务与网站设置保存于MySQL，已有选择优先；页面停用不等于暂停任务。UI按需创建，普通切页保留页面状态，停用页面释放其状态；不在包构造或启动时做数据迁移 |

`holder_report`/`holder_member` 与每项目一行 `collection_state` 是正式存储；报告期不是公告可用日。分析用途的来源质量限制与历史信号缺公告日期分别呈现，归档成功不等于任意用途都可用。

## 适用验证

来源与规范专项：`tests/test_ths_holders.py`、`tests/test_holder_combined.py`、`tests/test_holder_error_shapes.py`、`tests/test_holder_identity_gaps.py`、`tests/test_holder_quality.py`；共享 HTML 同时回归 `tests/test_ths_capital.py`。这些用例应覆盖一响应三栏、并列/缺序号、未知与零、同数异集、栏目未提供、空名债券隔离及首缺口恢复。

隔离恢复集成：`tests/integration/test_holder_archive.py`、`tests/integration/test_holder_run_outcome.py`、`tests/integration/test_holder_source_migration.py`；核对重复无业务DML、热摘要免SQL、有效修订、旧响应、防损坏补齐、SQL提交后重放、三栏事务回滚、成功清队以及后证券不等待前归档。迁移用例只在每例私有测试库验证，本次目录迁移不执行生产维护。

页面/装配：`tests/test_holder_ui.py`、`tests/test_holder_feature_lifecycle.py`，以及 feature bundle、装配语义与顺序、preparation、只读诊断、公共 UI 和文档可达性用例。安全实采工具测试为 `tests/test_source_verification.py`、`tests/test_verify_ths_holders.py`；工具的独占资源归属、停止失败不释放锁、清理后源码/配置复核和恢复-only失败路径均须单列。

真实来源验证入口为 `scripts/verify_ths_holders.py`，使用独立测试 MySQL 与本轮私有 Redis 前缀；正式来源仍为ths，正式配置只读。执行方法、配置及失败清理见 [来源说明](../../../../docs/ths-holders.md)。严格验收冻结随机至少30股及固定反例，实际代理请求、来源→规范化→Redis→归档→正式查询集合/内容和本轮队列零分别记证据；不替换失败样本。300398.SZ、601515.SH 的已知空名债券缺口须如实保留，不能通过白名单让严格验收打印PASS。

纯组织迁移只有在精确导入映射、运行AST、规范输入输出、全部稳定身份/顺序和恢复回归都证明语义不变时，才可按方案H3确定适用范围；仍要范围明确的正式端到端抽验。任何解析、请求、执行装配、恢复或消息变化均重新按实质修改准入。组织迁移通过、随机30股全通过、固定反例来源限制和实际已归档覆盖分别报告；静态等价、测试、性能、打包和真实桌面互不替代。