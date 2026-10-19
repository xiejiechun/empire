# D 股东复杂样板实施记录

当前状态：D纯组织迁移范围的开发、最终正式发布和同包真实桌面已完成；严格H3来源完整性仍失败，两个固定空名债券缺口保持。按请求前登记及手册D-07/验收6.1独立接受组织迁移，不把它记为30股严格实采通过。起点为main `120ddfc70376f40e6a798a71305b5713ecb8bb27`；整个优化未完成，E0～F尚未实施。各轮结论仅对应其所列输入。

## 范围与请求前适用性登记

八个原实现迁至 `features/holders/{contract,source,collector,dataset,query,audit,ui}.py` 与公共 `sources/html.py`。同步导入、测试 patch、显式 bundle、架构与装配映射、规则和文档关联；旧八模块退役，无转发。一个任务、一次必要 HTML 三栏、三个查询与页面、消息 schema 5、SQL proof contract 4、preparation revision 4、原槽位及用户配置保持。无 DDL、生产业务写入或历史证明维护。

在本轮首次来源请求前登记：产品采集实现属于组织迁移。八模块执行 AST 比对（排除导入、类型注解、两个原始输入类型别名及逐字段审阅的无方法 TypedDict 声明）一致；共享 HTML 字节完全相同，装配全部身份/语义/顺序检查通过。类型声明不改变原表达式、异常、默认值或请求/恢复分支。此判断仍须由业务专项、归档恢复、规范输出和实际有限链路支持，AST 不代替运行证据。

按 C/D/F 手册 D-07 及验收手册 6.1，组织等价范围与来源完整性分开结案。仍执行安全验证器的严格随机30加固定反例实采，固定 seed=20261019，不换样；保留 300398.SZ/2023-12-31、601515.SH/2024-06-30 空名债券。严格实采有缺口时 CLI 必须失败，不能写成30股准入通过。若来源存在原有缺口，只可在正式链路对所有有效记录及缺口证明核对无误、恢复等价等条件齐备后单独判断组织迁移；任何新解析、请求、消息或恢复行为差异均撤销该适用性判断并按实质修改验收。未取得这些证据前不得推进 E。

新增维护验证工具不属于第二条生产流程：`source_test_storage.py`、`source_verification.py` 仅创建 UUID 私有测试 SQL/Redis 资源，核实际 server_uuid、同连接锁及 owner，限制 SQL，失败保留并精确恢复。`smoke_source_storage_sql.py` 只用显式合成记录核现行初始化/正式归档查询，不请求来源。容量辅助 `capacity_session.py` 的 checkout 身份检查不是任意 SQL 语法防火墙。

## 起点与资源

工作区原为空；main 与 origin/main 同为120ddfc。安装 C release `8fbd5bd7a9cf460a9b82022b7e643f1d`、commit `81e147f35ba6af89b8b08219fe533130c875313c`，EXE SHA-256 `4196271f04b21eb8f987e8a000c6036dac7685dce04daab3e01bf92091926556`。

D旧应用器首先因 C 证据 method 的精确字符串不匹配拒绝；原证据完整值带 `; observed by root agent`，未改历史报告。随后发现120ddfc新增七项说明关联；新的本轮应用清单保留这七项。51项迁移及11项安全/类型/SQL smoke覆盖均保存实际前后像于本地 `build/architecture-d-20261019/`，没有整树覆盖 E 草稿。

已通过 computer-use 观察旧 C 工作台：活动采集0、待归档0；Alt+F4正常关闭后再次枚举无 Empire 窗口。需在验证结束重开。测试13348原来关闭，恢复原私有数据目录后实测 UUID=`a3e8a5eb-cb64-11f1-8ddf-380525361d4e`；生产3307 UUID不同，原实例不修改、不重启。原私有实例仅四系统库，flush=2。配置及插件偏好摘要已保存本地 environment.json，不包含密码；本轮最终还须逐字节核对。

## 已运行验证（仅限所列输入）

| 项目 | 实际命令/证据 | 退出码与结果 |
| --- | --- | --- |
| H1/H2、安全工具、类型与容量辅助反例 | `.venv/Scripts/python.exe -m pytest -q --tb=short -rs` 加11个明确文件；本地 unit1.log/xml | 0，720 passed，5.68秒；不涉及真实来源/SQL |
| C/R/U 公共与装配回归 | 同入口加22个明确文件；本地 common1.log/xml | 0，444 passed、18 SQLite deprecation warnings，32.93秒 |
| 类型 | `.venv/Scripts/python.exe -m mypy` | 0，6 source files；新增 holders/contract 严格检查 |
| 静态 | `.venv/Scripts/python.exe -m ruff check src tests scripts` | 0；初轮19项导入/未使用导入已修正 |
| C1/C2 装配 | `scripts/assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json` | 0，精确身份、语义、位置与完整顺序通过 |
| C3/C4 架构 | `scripts/architecture_contract.py check --output build/architecture-d-20261019/architecture1.json` | 0，333 modules、1318 imports、51 existing debt、0 new、1 retired |

## 本批补充实际验证

所有命令在项目根运行，Python为 `.venv/Scripts/python.exe`，私有配置路径显式传入且不公开正文。原始日志/JUnit保存在 `build/architecture-d-20261019/`；下列JSON为原文件逐字节归档，不改数值、日期或passed字段。

| 验收ID/范围 | 实际命令及证据 | 退出码、结果与限制 |
| --- | --- | --- |
| H2、R1～R4 隔离归档/恢复 | `-m pytest -q --tb=short -rs` 显式六文件：`tests/integration/test_holder_archive.py`、`test_holder_run_outcome.py`、`test_holder_source_migration.py`、`test_ths_capital_archive.py`、`test_prefetch_pipeline.py`、`test_archive_fairness.py`；`EMPIRE_INTEGRATION=1`、`EMPIRE_TEST_MYSQL_SETTINGS=build/architecture-evolution-20261019/mysql-settings.json`；integration1.xml/log | 0，116 passed，552.07秒；仅私有13348和独占Redis资源，不是生产覆盖 |
| D安全工具及Qt修复 | `-m pytest -q --tb=short -rs tests/test_source_verification.py tests/test_verify_ths_holders.py tests/test_capacity_session.py`；safety3.xml | 0，128 passed，2.60秒；含实际CLI QCoreApplication令牌生成子进程、输入漂移拒绝、资源归属及恢复；无来源请求 |
| D SQL正向smoke | `scripts/smoke_source_storage_sql.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --output build/architecture-d-20261019/sql-smoke2.json`；[原报告](architecture-d-sql-smoke-2026-10-19.json) | 0；55表真实初始化/metadata、配置初始/相同/修订及三栏两期正式归档、query/audit/preparation，pending0，6项清理成功；synthetic=true、source_requests0，不是30股实采 |
| H3严格来源完整性 | `scripts/verify_ths_holders.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --random-count 30 --seed 20261019 --proxy-only --timeout 1800 --output build/architecture-d-20261019/source2.json`；[完整原报告](architecture-d-source-2026-10-19.json) | **1，严格整轮FAIL**；池5580、seed20261019、30随机+18固定，48次全部代理、direct/fallback0；有效记录及缺口证明全部正式链路集合/内容一致，pipeline_verified=true、sample_30_met=true、strict_proxy_verified=true、pending0、6项清理成功。acceptance_complete=false；两固定空名债券仍存在，不能称H3完整性通过 |
| D持有人容量 | `scripts/measure_holders.py --test-settings build/architecture-evolution-20261019/mysql-settings.json --report build/architecture-d-20261019/holders-capacity1.json`；[原报告](architecture-d-holders-capacity-2026-10-19-1.json) | 0，10001报告/110400成员；import56.306秒≤180，allocated208175104≤536870912，重复业务DML0；所有原限值、完整测量、当前绑定及清理通过。合成容量，不是来源历史覆盖 |
| D资本容量 | `scripts/measure_ths_capital.py --test-settings build/architecture-evolution-20261019/mysql-settings.json --report build/architecture-d-20261019/capital-capacity1.json`；[原报告](architecture-d-capital-capacity-2026-10-19-1.json) | 0，700证券10500事实；import18.887秒≤30，重复业务DML0，audit2008.55ms≤10000；所有原限值、当前绑定及清理通过。历史213股来源事实不冒称本轮实采 |
| T3冻结性能 | `scripts/architecture_benchmark.py measure --test-settings build/architecture-evolution-20261019/mysql-settings.json --protocol docs/evidence/architecture-performance-protocol-2026-10-19.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output build/architecture-d-20261019/performance1.json`；[原报告](architecture-performance-d-2026-10-19.json) | 0，九指标median/p95共18/18通过，incomparable为空、cleanup=true；与容量/测试/桌面串行，原协议/阈值/基线/冻结工具未改。不代表真实桌面或网站吞吐 |
| 数据库设计门禁 | `scripts/verify_database_design.py` | 0，55 tables/49 datasets/12 JSON fields；仅将两项设计卡指向真实新容量，历史报告保留 |

首次source1在发请求前因CLI没有Qt应用失败（exit1、requests0、全部清理），[原失败报告](architecture-d-source-qt-failure-2026-10-19.json)保留；在开发CLI创建并保留QCoreApplication后，128项安全回归及上述source2验证。未改采集器/解析语义。初轮ruff的19项排序/unused修复、文档旧review失败、一次不存在测试文件的exit4、旧容量绑定失败均保留本地日志，后续通过不抹去这些事实。

## 组织范围适用结论与限制

H1身份、单响应三栏和公共HTML由精确装配、[迁移等价报告](architecture-d-migration-equivalence-2026-10-19.json)、业务规范输出专项及真实48证券链路共同支持。H2/R1～R4的旧版、同数异集、回滚、SQL提交后重放、成功清队、首缺口连续恢复、后证券独立归档由隔离业务/公共回归验证。U独立页面生命周期有真实PluginManager回归，三页均不启动采集/数据连接，停一页保持另一页能力，完整shutdown回收。公开契约严格mypy6文件通过。

按照请求前登记和D-07/验收6.1，本批仅组织迁移的开发适用项通过；H3来源完整性仍失败，不标已验收，也不改写原CLI结论。两个固定缺口为 `300398.SZ/2023-12-31`、`601515.SH/2024-06-30`，保持首缺口index15/fetch、48页168报告、无伪完整manifest；有效后续证券已处理。该范围不新增来源解析修复，不运行生产证明迁移，不修复或清除生产错误ID。新行为若改变此范围须撤销组织等价判断。

## 尚待执行或收尾

最终文档审阅/相关回归、完整正式发布、同包异cwd连接/查询/配置及真实桌面、证据提交和远程推送仍待完成；未完成前不进入E。13348自有测试实例仍运行，桌面目前正常关闭。远程只读核实曾因GitHub443连接失败，需重试。

## 首轮发布与桌面发现（后续修复需重新发布）

`b8fd9120805667c11196d4762dd17a37a456f4cf` 的 release `78cee05f837a4afa91c6075282bc41fb` 已完整运行唯一正式门禁，退出0，journal committed/passed；输入摘要 `1aa70a28a59536763d0185bc210e1afd8aba5da3ff6048e8c642acf5bd948204`。全量3623 passed、5 skipped、20 warnings，2503.09秒；跳过均为显式opt-in的state-unit，不计通过。包/配置/搬移smoke及切换通过。本地 `post-release1.json` 的只读核查通过：配置/偏好保持、安装身份匹配、异cwd真实连接、三栏正式查询及当时pending0。

真实桌面已确认版本、三栏列表/详情/分页/刷新选择、原任务策略、未保存31次重试草稿切页保留及滚轮不改值，随后撤销回原30，未保存测试配置；内置持有人帮助可读。尚未完成全部U项。返回采集管理时二级菜单变化但正文仍帮助，已保存 `desktop-navigation-recheck`，因此不标桌面通过。

用真实TasksPage/StorageHelpPage的离屏最小复现定位：`deactivate_page` 把帮助页名为 `scope` 的QLabel当成QueryScope，调用不存在的 `cancel_all` 抛AttributeError，中断切页。仅在具备可调用取消契约时处理作用域，不改变QueryScope本身、写命令、采集/存储/来源语义。新增真实两页面回归覆盖返回正文、筛选、只读取消、写命令保留及帮助搜索。`tests/test_page_lifecycle.py tests/test_navigation.py tests/test_collection_ui.py` 为exit0、47 passed/1.71秒，navigation1.xml；仍需完整发布和同包真实复验，首轮桌面失败证据保留。

## 最终发布前核对

此节原“最终”检查对应b8fd912首轮发布前输入；下面“桌面修复后的最终检查”取代其作为当前状态，不用历史通过覆盖当前失败。

最终ruff、mypy6文件、architecture（333/1318、51旧债务、0新债务、1退役）、assembly精确顺序及数据库设计门禁均exit0。最终文档review、verify_documentation（208篇/1437链接/55表）和三个文档专项 `tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py` 为exit0、30 passed/24.40秒，JUnit为documentation-final.xml。退役八模块生产/测试/脚本导入搜索无命中；release_lock、两性能工具、原协议和历史baseline的冻结摘要逐一保持。13348再次核实际UUID、端口及仅四系统库，无遗留私有业务库。

unit1.xml 的明确文件集合（命令为 `python -m pytest -q --tb=short -rs` 后接此集合及独占basetemp/JUnit）：

- `tests/test_capacity_session.py`
- `tests/test_holder_combined.py`
- `tests/test_holder_error_shapes.py`
- `tests/test_holder_feature_lifecycle.py`
- `tests/test_holder_identity_gaps.py`
- `tests/test_holder_quality.py`
- `tests/test_holder_ui.py`
- `tests/test_source_verification.py`
- `tests/test_ths_capital.py`
- `tests/test_ths_holders.py`
- `tests/test_verify_ths_holders.py`

common1.xml 的明确文件集合（命令为 `python -m pytest -q --tb=short -rs` 后接此集合及独占basetemp/JUnit）：

- `tests/test_all_collector_prefetch.py`
- `tests/test_architecture_benchmark.py`
- `tests/test_architecture_contract.py`
- `tests/test_archive_queue.py`
- `tests/test_assembly_contract.py`
- `tests/test_assembly_order.py`
- `tests/test_assembly_source_gate.py`
- `tests/test_collection_control.py`
- `tests/test_dataset_contributions.py`
- `tests/test_feature_bundles.py`
- `tests/test_fingerprint_versions.py`
- `tests/test_ingest_reservations.py`
- `tests/test_manager.py`
- `tests/test_prefetch_budget.py`
- `tests/test_preparation.py`
- `tests/test_preparation_directory.py`
- `tests/test_project_diagnostics.py`
- `tests/test_ths_capital_lifecycle.py`
- `tests/test_ths_capital_transport.py`
- `tests/test_ui_architecture.py`
- `tests/test_ui_architecture_counterexamples.py`
- `tests/test_unit_prefetch.py`

## 桌面修复后的最终检查与未通过项

第二个真实缺陷：843×643窄窗口可拖动名单正文滚动条，但鼠标滚轮不移动正文。公共过滤器把QScrollBar作为QAbstractSlider一并拦截。先增强真实QScrollArea回归，wheel-before.xml为exit1、1 failed/1 passed，实际滚动值仍0；随后排除QScrollBar，保留数字框、下拉框、QSlider、QDial的防误改。新增QTextBrowser和QTableWidget实际滚动验证，interaction3.xml为exit0、51 passed/2.30秒。两处修复均不涉及来源、消息、归档、SQL或容量工具绑定；没有仅刷新容量hash。

最后两项代码修复后，ruff、strict mypy（6文件）、architecture（333模块/1318导入/51旧债务/0新债务/1退役）及精确assembly检查逐项exit0；architecture-wheel-final.json。最后合并回归命令为 `.venv/Scripts/python.exe -m pytest -q --tb=short -rs tests/test_desktop_interaction.py tests/test_page_lifecycle.py tests/test_navigation.py tests/test_collection_ui.py tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py tests/test_ui_architecture.py tests/test_ui_architecture_counterexamples.py --basetemp build/pytest-d-wheel-final --junitxml=build/architecture-d-20261019/wheel-documentation-final.xml`，exit0、104 passed/57.40秒。程序内入门和日常浏览已说明滚轮及切页/草稿行为，现有页面覆盖关联适用；最后文档review已执行。这些仍不是新包真实桌面证据。

以下每轮均使用原冻结完整命令（上文T3行，仅`--output`不同），没有选择或删除单次samples。报告中的测量passed与comparison.passed分别保留，不把可比/cleanup成功等同统计通过。五个冻结文件、协议、原baseline、阈值均未修改。

| 本地输出 | 正式原始报告 | 命令退出码 / 18项中失败数 |
| --- | --- | --- |
| performance-navigation2.json | [failed2](architecture-performance-d-navigation-failed2-2026-10-19.json) | 1 / 13 |
| performance-pre-navigation-control.json | [修复前同机对照](architecture-performance-d-navigation-control-2026-10-19.json) | 1 / 9 |
| performance-navigation3.json | [failed3](architecture-performance-d-navigation-failed3-2026-10-19.json) | 1 / 9 |
| performance-navigation4.json | [failed4](architecture-performance-d-navigation-failed4-2026-10-19.json) | 1 / 14 |
| performance-navigation5.json | [自有MySQL正常重启后failed5](architecture-performance-d-navigation-failed5-2026-10-19.json) | 1 / 8 |
| performance-navigation-wheel6.json | [两修复failed6](architecture-performance-d-navigation-wheel-failed6-2026-10-19.json) | 1 / 12 |
| performance-final7.json | [最终failed7](architecture-performance-d-final-failed7-2026-10-19.json) | 1 / 9 |

最终第7轮在全部104项回归结束后单独执行，2026-10-19T09:52:49Z，source摘要与原始报告一致，correctness可比、cleanup=true。失败项为news_next median、news_search p95、holders_browse median/p95、holders_detail p95、news_ui median/p95、holders_ui median/p95。最终D适用T3失败，不能引用16:05首轮通过放行。

对照采用git show的b8fd912前像临时还原帮助生命周期及正文，finally逐字节恢复本轮文件，performance-control-operation.json记录restored=true。不是reset/clean；LF与工作区CRLF的输入摘要差异如实保留。诊断cProfile和native thread-CPU测量另外保存本地，带剖析开销，不能作性能验收；后者session27801已结束，exit1。setHtml累计wall764.78ms/threadCPU750ms，不足以把超限归因于等待。当前普通优先级、AC供电、无显式进程节流；机器有其他应用活动，尚未确定根因，也未改变电源、优先级、亲和性或关闭他人应用来凑通过。

首轮包额外真实U1核查：停一项持有人UI时另两页及三查询/采集保持；停collector后任务和历史仍可读，从页面继续采集被正式禁用保护拒绝，未发请求；全部恢复。普通停用Redis基础插件被现有依赖保护拒绝，未级联停服务。原10项插件偏好在正常关闭后按environment.json的原hash逐字节恢复，测试后全偏好副本只保留build。源/程序config均未写入。上述生命周期、窄窗及草稿观察属于b8fd912旧包，修复后同包复验仍未完成。

**17:56检查点退出结论：D最终验证失败，未验收；E0未开始。** 安全/业务/容量及首轮发布事实保留，H3严格来源FAIL保留；两UI修复当时未重新正式发布。不得把该检查点当作成功发布或整个任务完成。后续进展单列下节，不修改这些原失败报告。

检查点实现及失败证据提交`7b0c69baf9ddc69e9870db177859601668c89d97`已推送main，Git push exit0，随后ls-remote精确匹配。GitHub直连多次443超时后，Git进程仅本次使用已核租约的node004代理环境，不保存配置、不输出凭据、不更改用户日常策略。

检查点[正式包只读原报告](architecture-d-checkpoint-runtime-2026-10-19.json)为exit0，明确绑定首轮release `78cee05f837a4afa91c6075282bc41fb`，actual_desktop=pending字段原样保留；它核同包manifest/tree/EXE、两份config和插件偏好、异cwd doctor及正式query。当前源码新增UI修复未进入该包，不能由此报告推导修复桌面通过。[自有实例关闭原记录](architecture-d-checkpoint-resources-2026-10-19.json)在17:56:03北京时间前后核实际UUID/datadir、仅四系统库、other_client_sessions=0，正常SQL SHUTDOWN后13348端口关闭，数据目录保留。没有停止生产3307、清共享Redis或删除生产业务。

随后通过computer-use重新启动同一正式EXE，fresh窗口71765144可见，工作台显示本地服务连接、45任务、当时活动0/待归档0；新闻日常任务17:56:35完成。实际截图和树保存本地`desktop-checkpoint-restored.png/json`，这是一时快照，后续日常采集会继续。最终再次核五项冻结文件及根/程序config、原插件偏好hash均保持；无遗留测试进程。下次需验证时先正常关闭该桌面，并重新核实或启动自有实例，不能凭旧PID清理。

## 19:25恢复调查与正式T3复测

用户补充“没有已知变化”，因此没有将电源或重负载变化写成根因。重新正常关闭桌面，fresh窗口为空；重新启动仅本任务自有13348，SQL实测UUID/datadir、64MiB buffer、flush=2与冻结协议一致，仅四系统库。生产3307与共享Redis未重启。最新正式实现HEAD为c037b49，产品修复仍为7b0c69b的相同字节，没有为性能改产品、工具、协议或基线。

进一步核对冻结基线、C和当前news/top/float/bond四张1280×800离屏PNG逐字节相同，未发现渲染内容/布局负载差异。随后预先固定A–B–A诊断顺序：默认进程、仅本进程显式正常execution-speed提示、再默认进程。使用本地`diagnose_process_qos.py`，子进程退出即结束提示；未写机器电源/优先级/亲和性设置。三轮[诊断原数据](architecture-d-qos-diagnostic-2026-10-19.json)均明确diagnostic_only，绝不计验收。A仅holders_detail p95超限，B仅news_first p95超限，A2全统计通过；两默认进程也恢复低耗时，不支持“提示解决性能”的归因。当前仍未确定瞬时超限原因。

诊断后单独使用未修改的正式CLI完整重测：`.venv/Scripts/python.exe scripts/architecture_benchmark.py measure --test-settings build/architecture-evolution-20261019/mysql-settings.json --protocol docs/evidence/architecture-performance-protocol-2026-10-19.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output build/architecture-d-20261019/performance-resumed8.json`，**exit0、18/18通过**，incomparable为空、cleanup=true，实际结束时间2026-10-19T11:25:22Z。[逐字节正式原报告](architecture-performance-d-resumed-2026-10-19.json)保留全部samples。source摘要仍为`e196646edd4a251063e5f89ae415d63be8fe6558f31d680f110087d8f9a58c6d`，与失败第7轮完全相同；五项冻结文件摘要逐一保持。

这份结论仅证明本轮原协议内全部统计通过，不证明已找到失败根因，也不抹除前七轮失败或扩展为真实桌面速度结论。未选择单项最快样本拼接报告。原104项回归、两份容量及其绑定未改变；当前D组织迁移开发适用项通过，重新发布和同包真实U项仍待完成，H3严格来源完整性FAIL不变，E0未开始。

## 最终正式发布与同包真实桌面

唯一正式入口 `./verify-release.ps1` 已自然结束，exit0；未另起发布或修改冻结输入。release `de8532b2a7f146d184964805b5694b66` 的 publication 为 committed/passed，绑定干净提交 `b7f452adcd51da1ae61d7dde643789497dea7c45`；完整输入摘要 `63ef47703e4f2d553f638d03585e2c01a287aa001328a763237b3527ab6ddbbd`，EXE `8b2a59b9592b7b8e0bfc9cf5f89d922709cbb75a8e9e8de52737e50afd1cb644`，安装树 `ea9b1421cd4be510e92180bbc4b5f9eecd35773092954b2408dc764b7ed71bae`。权威本地 journal 为 `build/releases/de8532b2a7f146d184964805b5694b66/publication.json`；24步日志、retained evidence、JUnit保留。

全量 **3626 passed、5 opt-in skipped、24 warnings，2253.15秒**，无failure/error。5项state-unit跳过不计通过，本批未改该恢复协议。4条新增警告来自预期非零PowerShell子进程输出的UTF-8解码；非零及调用断言通过，随后只以 `PYTHONUTF8=0` 重跑同4项，exit0、4 passed、无警告，`entrypoint-encoding.xml`；未改产品或冻结工具。独立容量、四档DPI、PyInstaller、包/异cwd/搬移/配置smoke与切换全部通过。

同包真实窗口使用 computer-use/sky 观察和操作，原窗口1183900，正常退出后fresh枚举为空；最后重开窗口126750622可见。实际三栏名单、详情、债券第二页（688401.SH/2026-06-30路维转债）、来源排名提示和长基金名称可读；835×643窄窗正文滚轮26→276→26，最大化正文0→42。流通股东选中600368.SH/2026-10-12刷新后选择和正文保持；股东920296.BJ/2026-10-21的未来报告期警告保留，未改造数据。

帮助页可阅读同花顺持有人说明，窄窗正文实际滚轮0→270；从帮助返回采集管理后正文恢复TasksPage，31次未保存重试草稿保留，并经历后台刷新。数字框及网络下拉框真实滚轮后仍为31和“代理优先，可回退直连”。最终撤销至原30，保持每天20:00及原网络策略，没有保存测试设置。窄窗撤销按钮首次自动定位在可见窗口外，工具拒绝操作；最大化后才完成撤销，不把被拒动作记成功。

同包U1：单停债券UI时其状态已停用，其他两UI、三查询及collector仍启用，股东真实正文仍可读；恢复后再单停collector，任务管理/历史继续可读，“继续采集”回执为“该采集插件当前未启用”，活动任务仍0，未启动采集。恢复collector后，普通停用Redis被依赖保护拒绝，状态栏列出collection/HTTP/archive/ingest等依赖，Redis仍启用；未点级联。

正常退出后保存本轮全量偏好快照，确认它与先前已核的全启用快照逐字节相同，无额外差异；从本会话原10项键恢复出的字节必须精确匹配开工SHA才写回，保留测试后副本，不凭猜测覆盖。两份config均未写入。执行 `.venv/Scripts/python.exe build/architecture-d-20261019/check_published_runtime.py --run de8532b2a7f146d184964805b5694b66 --report build/architecture-d-20261019/post-release-resumed-after-desktop.json`，20:57 exit0：包manifest/EXE/tree、config/原偏好、C:/Windows正式EXE doctor的Redis/MySQL真实连接、三栏browse/detail/第二页集合一致，服务正常回收，检查时全局pending0。该[只读原报告](architecture-d-post-release-2026-10-19.json)仍保留actual_desktop=pending，实际桌面事实由本节及独立窗口记录证明，不修改原报告冒充自动验收。

重开后的真实工作台显示45任务、活动0、待归档0及连接正常。日常计划随启动恢复，20:11～20:24持有人自然运行仍报告来源缺口；生产股票数已随日常采集从5580变为5579，未删除业务数据或把不同时刻读取称原子快照。该动态全局状态不替代私有48证券实采的pending0。

最终只读审阅命令 `.venv/Scripts/python.exe build/architecture-d-20261019/audit_final_evidence.py`，exit0；[审核输出](architecture-d-final-evidence-audit-2026-10-19.json)复核当前两份容量全部bindings/清理、T3源身份/18项/冻结物、严格来源FAIL/清理、正式JUnit及journal/同包运行身份和窗口可访问树。脚本最初把harness集合摘要错当单文件摘要而拒绝，改用原冻结工具的公开计算方式后通过；没有改任何被审报告、harness或阈值。

| 验收ID | 适用范围、结果和证据 |
| --- | --- |
| H1、C1/C2 | 通过；一个任务/一次HTML三栏、独立查询/页面、身份与六类顺序保持；装配、migration-equivalence、业务专项及48证券正式链路 |
| C3/C4 | 通过；八旧模块和调用方退役、无转发/双登记，architecture新债务0；搜索、assembly及最终完整门禁 |
| H2、R1～R4 | 通过；unit1/common1、116项私有集成及最终全量覆盖旧记录补齐、冷热摘要、同数异集、首缺口恢复、取消/清理、独立入队归档和提交后重放；不扩展为生产全市场完整 |
| H3严格来源完整性 | **失败，exit1**；30随机+18固定/48全代理、pipeline一致、pending0/清理成功，但两固定空名债券使acceptance_complete=false。完整原报告保持，不能称严格整轮通过 |
| D组织迁移的实采适用判断 | 按首次请求前登记及D-07/6.1独立接受；生产采集表达式/异常/请求/恢复/消息契约不变，逐模块等价、规范输出、身份/顺序、私有恢复及48证券正式E2E俱全。新工具为显式私有维护，不替代生产路径；两公共UI修复另经行为回归和同包桌面验证。此结论只放行组织迁移，不豁免未来实质采集变化 |
| D安全、容量、类型 | 通过；128项安全/恢复、SQL正向smoke、两份真实新容量且当前绑定匹配、strict mypy6文件；所有原协议/规模/阈值保持 |
| T3 | 当前最终原冻结完整命令18/18通过；前七轮失败原样保留，原因未确定；不由一次通过推定已修复瞬时超限 |
| U1 | 同包真实启停/拒绝/恢复完成；共享服务依赖保护生效，原偏好精确恢复 |
| U2 | 同包帮助正确返回、草稿切页/刷新保留并撤销、滚轮保护/正文滚动、刷新选择与窄窗长名单均完成；只读取消/写命令保留由104项相关回归及完整门禁支持 |
| U3、A4适用发布项 | 同一b7f452a包、干净身份、异cwd真实连接、正式查询、原设置/偏好和正常关开完成；5 skipped及警告如实单列 |
| M3、T2的D适用部分 | 路径/用户正文/coverage同步及最终审阅通过，持有人公开契约纳入6文件strict mypy；不扩展为F全部公共边界已完成 |
| M1/M2、T1及T2的F增量 | 本批不适用；D未实现F定位演练、单源聚合、影响报告、其余公共类型或测试成本优化，不提前计通过 |

**D已验收仅指上述组织迁移和两项UI修复范围；H3严格来源完整性仍失败。** 全部对应命令、退出码、输入及限制见本记录；原始本地窗口树/PNG以`desktop-resumed-*`命名，其摘要/时间见审核输出。后续纯证据提交不改变已发布包身份；须完成文档契约、提交与远程核实后再进入E0。E0～F仍未开始。

纯证据文档的最终检查：`documentation_contract.py review/check`、`verify_documentation.py`（208篇/1451链接/55表）及`verify_database_design.py`均exit0；`.venv/Scripts/python.exe -m pytest -q --tb=short -rs tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py tests/test_storage_help.py --basetemp build/pytest-d-accepted-docs --junitxml build/architecture-d-20261019/accepted-docs.xml`为exit0、35 passed/33.76秒。没有改变产品源码、包内资源或既有验收输入，按纯证据流程处理，不重复发布。
