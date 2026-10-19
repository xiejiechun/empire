# E4 开盘啦七项实施记录

当前组织迁移范围已完成正式发布与同包真实桌面验收；严格来源FAIL保留，E5尚未开始。实现提交acb466a，release 61dc981193d24b50bc84bee1c9ca1670；结案提交推送核实后才进入E5。下列开发检查点保留原历史时态，最终事实见末节及[真实桌面](architecture-e4-desktop-2026-10-20.md)。

## 请求前范围登记

本批24个旧模块迁入features/kaipanla，同步调用方并删除旧入口；产品、任务、数据集、消息schema、页面、表键、来源参数及解析、下载、入队、归档恢复语义保持。共享schema_manifest改为显式schema_contract(tables)，业务表组从唯一business-schema读取；复权改用连接内惰性iter_validated_days，保留既有事务快照。新增接口的行为须独立测试，不用AST等价替代。

来源采集体及其规范/恢复为组织迁移，按acceptance 6.1判断本批来源实质变更不适用；源码逐定义及集合/恢复证据仍需最终审阅。本轮额外执行随机30股和固定反例，不用组织适用性把严格来源失败改成通过。请求前冻结种子20261020；完整当前正式池由共享验证器排序、记录池摘要并抽样，五固定证券002731.SZ、920112.BJ、920175.BJ、920304.BJ、605333.SH额外加入。随机及固定合并样本日期2026-09-30；五固定证券另核2026-09-28～30，覆盖原34缺口的全部证券及日期。不能换样、填零或清未解决错误。

正式日历整月与所选证券有限生效停牌记录通过单一READ ONLY一致快照读取，校验精确日期及交易标志、记录实例及内容摘要；仅限制验证器规划，不伪造空私有库历史覆盖、不声称停复牌全部来源完整。上市资料仍由正式采集器真实请求。采集使用共享代理、正式预取、原子入队、唯一统一归档、正式day及完整分页集合内容核对。旧同名脚本已替换为共享PrivateStorage生命周期；实际SQL守卫smoke、取消/归属/清理反例通过后才请求真实来源。

## 已执行与待执行

- 58项隔离集成通过，126.56秒，exit0：开盘啦归档/停牌范围/预览查询/存储/复权；本地integration-1.xml。
- 首轮领域186通过/2失败：旧容量报告绑定退役路径，失败保留，待新报告登记后复验。
- 私有生命周期、SQL守卫、取消/清理、容量及来源观察器反例133通过，1.85秒，exit0；verifier-1.xml。
- 新容量实际测量exit0：七kind真实样本及100000同秒点，原预算；页P95 2.976ms、时段2.981ms、后页5.175ms、Python峰值252117字节、有限整日9.013ms，所有清理项通过。旧报告原样保留；新报告不等于全市场容量或当前v2写入实测。
- 实际SQL守卫smoke、真实来源、最终类型/公共回归、T3、文档审阅、正式发布及真实桌面尚未完成。

本轮资源：自有13348实际UUID a3e8a5eb-cb64-11f1-8ddf-380525361d4e，测试datadir保持；桌面在E4前已正常关闭，收尾须重开。生产3307、共享Redis、配置及偏好保持；旧停复牌错误38622b7215a44fe4a5224031bdf4d963未修未清。

## 验证器修复与失败保留

source-1在真实请求前被严格私有SQL守卫拒绝：依赖参考读取时机错误；清理全部通过。增加共享生命周期的可选只读prepare_scope，在冻结名单后、私有守卫建立前读取已审有限参考；没有放宽守卫。新增顺序及准备失败不建资源反例。

source-2七kind的有效来源、Redis入队、正式day及全部分页一致，每子范围pending0，整体pipeline_verified=true、acceptance_complete=false、严格exit1，六项清理均true、无剩余私有SQL/Redis。原五固定反例保留，随机样本另发现竞价920161/920665、委托603073/603210/605255/688712/001202/002216/300564和大单920161/920174/920665范围缺口，不改来源规则或换样。

该旧轮通用sample_30_met字段错误地由pipeline_verified回退计算为true，**不采信该字段**，不能作为30股全成功。已增加逐随机证券expected/source/query集合及内容的严格派生，含来源缺口、同数错键、内容变化、无有效单元四种反例；历史固定子范围明确引用本kind随机结果。另对停牌参考先按当前子范围证券过滤，避免带入其他证券。修正后的最终144项安全/观察器/公开输入测试exit0、1.71秒，mypy八文件及全src/scripts/tests ruff通过；待同一种子、同一原名单完整重验，不删首轮原报告。

七kind实际守卫SQL smoke-4通过，均pipeline/完整查询通过、六清理true，明确合成/source_requests=0，不冒充实采。容量首轮保留；最终工具增加原30次计时的全部原始样本和实际环境，需重新实际测量并更换新报告，不刷新旧hash。

source-final诊断轮也保留为严格失败。其random_coverage将尚未附市场/上市关联的解析摘要与完整规范记录摘要比较，导致有效随机单元被保守拒绝；实际来源→入队→查询的逐记录相等断言通过。修复仅统一验证器报告摘要口径：来源加上已独立核对的市场和真实上市关联后计算规范摘要，和正式查询使用相同字段集合。实际七kind守卫SQL smoke新增source_units/query_units精确相等断言，避免仅看流水线标志。144反例/公开输入复验通过，1.82秒。程序内开盘啦主题和技术维护正文同步完成后再执行同一名单新轮，避免旧正文摘要桥接。

数量说明：source-2的350是含35次固定日期重查的单元观察数，不是不同业务键数量。必须以kind/证券/日期去重核对，本批最终报告分别列观察与不同键；不从相同条数推断无遗漏。

## 最终开发检查点（05:31）

以上“尚未完成”段落是较早检查点，以下为当前事实。最终实采原报告source-verified.json自然退出1，严格FAIL；[逐范围机器审阅](architecture-e4-source-audit-2026-10-20.json)退出0，逐项确认14子范围的expected/source/query集合、内容摘要、分页、失败不推进complete及pending0。正式池5579只，种子20261020，30随机加5固定名单与source-2完全相同。519次共享代理请求，直连/回退0；350次单元观察包含35次重复固定日，315个不同业务键中269有效、46缺口；六cleanup全true、remaining SQL/Redis均false。trend/volume/trades/quote的30随机单元成功；auction/entrust/large_order仍有随机来源缺口；五固定历史反例保留，不能宣布随机30股整体验收通过。本批不修改来源参数、解析、失败规则或恢复语义，组织适用性依据请求前登记和逐定义/真实管线证据，不事后豁免来源FAIL。

实采结束后只改帮助换行和一个测试入口：[最初帮助字节桥接](architecture-e4-help-newline-bridge-2026-10-20.json)、[最终760输入逐字节桥接](architecture-e4-final-input-bridge-2026-10-20.json)均实际重构出原实采source_sha256。帮助删除5691个多余CR，文字未变；test_listing_scope_prefetch直接从dates导入required_days，两个断言不变，未给listings_source新增兼容转发。其余运行Python、验证工具、SQL、fixture、配置字节完全未变；测试修复以新回归和完整门禁验证，帮助以最终契约及真实桌面验证。原实采报告不改写。实采原输入af600a2c6d11d3c2236197d1b60b8a749cc0b7546a17c8259505488bc9d84c5f；当前业务证据输入54f7b5a8d838f567c10b00dda4a37b936fe497641918d8f097cf7deb620c6429，不能与发布或T3算法混同。

最终容量命令为`.venv/Scripts/python.exe scripts/measure_preview_queries.py --test-settings build/architecture-evolution-20261019/mysql-settings.json --output build/architecture-e4-20261020/kaipanla-preview-capacity-2.json`，自然exit0。未改写复制到[最终容量报告](architecture-e4-preview-capacity-final-2026-10-20.json)，七设计卡已更新。七真实kind齐全，100000同秒分笔，全部原始30计时保留；页/时段/后页P95分别3.151/2.969/4.712ms、峰值252328字节、整日8.523ms，原10ms/350000字节/100ms阈值全部满足，六项清理true。17份active measured报告按当前实际绑定扫描全部有效；首轮旧报告原样保留，不当作最终绑定。此为热查询和有限证券日，不冒称当前v2完整写入/全市场容量；DDL和写入语义未变，历史v1写入实验保留原范围。

| 验收编号与范围 | 实际验证、退出码及证据 | 限制/待办 |
| --- | --- | --- |
| C1/C2、E4身份 | assembly_contract snapshot/check，原baseline、mapping、order-baseline；exit0。插件/任务/能力/dataset/job/schema/页面及原槽位精确相同 | 不是仅数量相等 |
| C3/C4、旧路径 | architecture_contract check --output build/architecture-e4-20261020/architecture-final.json；exit0：377模块、1402导入、14旧债务、0新增、33退役；24旧文件删除、全部运行调用方同步 | 整个F共享治理尚未实施 |
| E4/R1/R2及公开输入 | domain-final2.xml，279 passed/18既有sqlite日期适配警告/5.82秒/exit0；首次扩展277pass/2fail为测试拆分入口遗漏，修复后新轮通过 | 无新增兼容层；保留两轮失败 |
| R1/R3/R4隔离业务 | integration-1.xml，58 passed/126.56秒/exit0；覆盖产品归档、旧版、冷热摘要、失败留队、提交后重放、停牌范围、预览及复权快照 | 最终完整门禁再执行；不是生产全历史审计 |
| R2/R3/R4公共生命周期 | public-final.xml，274 passed/22.25秒/exit0；含装配、manager、source_verification、私有容量归属、预取/预算和入队竞态 | 模拟故障与真实SQL smoke分别记录 |
| 安全工具/SQL smoke | verifier-verified.xml，144 passed/1.82秒/exit0；sql-smoke-verified.json exit0，七kind source_units/query_units完全相同、source_requests0、sample_30_met false、六清理true | 明确合成SQL正向smoke，不冒充实采 |
| 真实来源6.1 | 同一冻结池/名单、全代理、正式链路，严格exit1；机器审阅exit0，source-verified-audit.json | 来源缺口FAIL；本批纯组织适用性与严格实采分开判断 |
| 容量8 | 当前七设计卡、容量2原样报告；17份实际binding全部有效，exit0 | 旧v1写入实验不扩为当前v2完整容量 |
| T2当前公共API | `python -m mypy`，8严格文件exit0；`python -m ruff check src scripts tests` exit0 | 不宣称全项目严格类型 |
| T3 | [本轮冻结性能](architecture-performance-e4-2026-10-20.json)，原measure命令、原protocol/baseline/test-settings，exit0，18/18、incomparable空、内容正确、cleanup true | 原工具/阈值未变；offscreen UI不等于真实桌面；不推断网站吞吐 |
| M2/M3本批说明 | 七页面/任务正文、业务README、规则coverage、结构/存储与安全工具说明已同步；最终review/check待执行 | F单源帮助工程尚未实施 |
| U1/U2/U3、正式发布 | 尚未执行本批唯一发布及同包实际验收 | 不能沿用E3安装包或桌面 |

T3实际命令：`.venv/Scripts/python.exe scripts/architecture_benchmark.py measure --protocol docs/evidence/architecture-performance-protocol-2026-10-19.json --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output build/architecture-e4-20261020/performance-final.json`。原始样本、同机依赖/字体/MySQL、输入和比较全保留。

日常生产数据、两个config、插件偏好、45任务原保存策略保持；本轮私有来源样本清理不涉及生产错误。停复牌旧错误38622b7215a44fe4a5224031bdf4d963未修未清，D空名债券严格H3失败与E5分红完整容量待办不变。当前尚未正式发布和可见桌面，不能进入E5。

最终文档审阅由正式documentation_contract review完成，逐对象给stock、九KPL表和preparation-report具体不变理由；七页/任务正文实际同步。review/check、verify_documentation（225文档/1538链接/55表）、verify_database_design（55表/49数据集/12 JSON字段）均exit0，35文档回归/27.00秒/exit0。发布前[机器审阅](architecture-e4-pre-release-audit-2026-10-20.json)重算原始T3样本、核七组JUnit（含历史失败）、24旧路径及零Python遗留引用、760输入桥接、17容量绑定、冻结工具和原config/偏好；实际exit0。随后只读preflight-final.json再次确认自有13348实际UUID/datadir、仅四系统库且无其他客户，生产实例不同、global pending0，48行保存设置已取精确前像。此后冻结输入和HEAD执行正式发布，U1/U2/U3尚待本包实际验证。

## 正式发布与最终适用出口（06:43）

唯一命令 `./verify-release.ps1` 自然exit0，release `61dc981193d24b50bc84bee1c9ca1670` 的publication为committed/passed，冻结干净提交 `acb466aa64589400b1eea5d03abf3ee8a99a36dd`。完整输入 `508a4fffaf9649b9d094aeae084269425d1ed34188a31cd6bbb4fb3d150f3b2a`，EXE `e6a1bd55912081d8b10846d314aedc1c9e9017aed683f4a23d8a9c66339e8a22`，安装树 `308efcdd6a3912196a0a7e535791ddde6bbaadb88224331a1e51cbb56a25ad3e`。

3755 passed、5显式opt-in skipped、20弃用警告，pytest 2168.72秒；24步骤、独立容量、四档DPI、打包和搬移/config smoke及正式切换均满足原门禁。第22步首次模板生成预期exit1，后续复核exit0，不将它伪记为exit0。`.venv/Scripts/python.exe build/architecture-e4-20261020/audit_release.py` 实际exit0，逐字节核1528输入、54保留输出、24步骤及原JUnit；[原样审核报告](architecture-e4-release-audit-2026-10-20.json)保留每步退出码和输出摘要。5个state-unit跳过仍为未执行，本批不修改该opt-in状态契约。

| 验收编号 | 本批最终结论与证据 | 限制 |
| --- | --- | --- |
| A4、U3 | 上述完整门禁及[同包复验](architecture-e4-post-release-2026-10-20.json)，exit0；包内manifest、真实异cwd连接、七项正式查询/完整分页、配置保留 | 机器查询使用冻结源码API与安装配置；包内doctor和可见七页独立验证 |
| U1 | 单停竞价UI和采集器、恢复；盘口采集器停用拒绝相关任务；其他任务/历史/查询可用；直接停分时查询被依赖保护拒绝 | 真实动作范围见[桌面记录](architecture-e4-desktop-2026-10-20.md)，未遍历全部插件组合 |
| U2 | 草稿2→3未保存，滚轮/切页/后台刷新保留；撤销回2；903×892实际窄窗、滚动与保存栏通过 | 惰性/取消/写入竞态由专项及全量回归支持，未冒充全部桌面复现 |
| U3、正常关开 | 48行SQL设置payload及updated_at、两config精确保留；159开关恢复后审计还原原偏好；Alt+F4后fresh枚举空，再重开3345610可见 | pending0/活动0为06:42动态事实，后续原日常任务继续 |
| M2/M3 | 安装包真实主题/数据说明可读，正文与coverage在实现提交同步；结案只更新事实记录并重做文档契约/相关回归 | 不改变本次已发布EXE身份；F单源帮助仍未实施 |

本批C1/C2/C3/C4、E4/R1/R2/R3/R4、T2/T3、容量和M/U适用出口已有上表及开发矩阵证据。严格来源验收仍exit1、sample_30_met=false、acceptance_complete=false；269有效/46缺口、519代理/直连0/回退0、私有pending0与全部清理保持原报告。组织范围在请求前已明确，未修来源语义，不以发布和桌面通过冲销严格来源FAIL。H1/H2/H3为D持有人专项，本批不重做；D已知H3失败继续保留。

下一项E5必须先审阅完整分红容量协议并实现安全工具，再按资本行为/复权实际前像逐项迁移，不应用整份E草稿。E5～F未完成，整个模块化优化尚未完成。

结案文档review/check、verify_documentation（226文档/1551链接/55表）、verify_database_design（55表/49数据集/12 JSON字段）均exit0；同四文件文档回归新轮35 passed/27.20秒/exit0，原JUnit为 `build/architecture-e4-20261020/docs-close.xml`。结案资源只读命令 `close_resource_audit.py` exit0：自有13348实际UUID/datadir不变，仅四系统库、无其他客户连接；冻结工具保持、正式包身份保持、当时global pending0。程序窗口3345610继续可见；生产MySQL/Redis未关闭，未清旧错误或业务数据。
