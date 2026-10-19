# E0 SQL归属资源实施与验收记录

状态：E0已完成开发验证、正式发布及同包真实桌面验收，2026-10-19，北京时间。最终证据审阅通过；本次结案文档待提交推送，推送核实后才进入E1。D严格H3来源失败保持独立结论。

## 首轮正式门禁及修正

实现提交`9041792f9c769b0d28d7bcbaba6fb05578666058`，干净工作区。唯一入口`verify-release.ps1`首轮run `d62f83b5b2c94ab2913fbade77a2f867`退出1，在step-003文档校验拒绝过期审阅；Python/42依赖已过，未开始pytest、打包或切换。根因是最后review之后又更新了coverage.guides中的status.md，改变整体说明摘要，之前开发check的通过不能覆盖该后续变化。保留`failure.json`、inputs和step-003完整日志；未改发布保护或绕过文档检查，D原包仍保持。

修正仅补最终状态和事实后重新实质审阅，再提交文档并从唯一入口完整重跑；不改产品源码/冻结性能输入，因此最终性能报告仍绑定同一业务输入。后续审阅通过前不再修改任何coverage指南正文。

## 输入、范围与旧入口

前批D组织迁移已验收，严格H3空名债券失败原样保留，见[D记录](architecture-d-2026-10-19.md)。本批前像为main `08fe382677298ee4b2e650fce50cfcca0aa0b868`，开工工作区干净；21:17有界`git ls-remote origin refs/heads/main`退出0且精确匹配。正式安装仍为D包`de8532b2a7f146d184964805b5694b66`。此前代理远程核实无输出卡住，取消自有命令后直接核实成功，不写为代理检查通过。

本批把[公共归属模块](../../src/empire/contracts/business_schema.py)原先从KPL/THS资本导入并计算的五组映射转为[单一显式资源](../../sql/business-schema.json)，退役公共模块内的业务导入与推导表达式。保留原公共API路径、五组值/类型/顺序、stock双源、news无限制、资本必需unified_code、三项显式主键例外及原异常语义。新增严格资源读者和dataset_tables；资源缺失、损坏、重复字段或非法归属明确失败，没有旧常量回退。业务侧KPL/THS资本接线留至E4/E6a。

调用方仍通过contracts.business_schema使用固定来源、归档与查询schema及显式维护清单；各业务dataset/query、维护脚本无需改公共入口。Empire.spec加入资源；verify_database_design显式读取传入root，核实际数据贡献、DDL形状、必需列及旧source列；documentation_contract/storage把JSON及逐表归属纳入全局、可达和表级审阅摘要。当前正文仅插入“程序资源与维护”章节，保留D帮助/滚轮修复及既有业务说明。

本地前像、完整旧映射类型/顺序、每文件原字节和hash：`build/architecture-e0-20261019/preimage.json`及`preimage/`；精确上下文重基器`prepare.py`。不是整体应用E树；13个候选文件分别应用，对当前内容逐替换且断言前像唯一。新增专项另外补资源初始化和非法标识反例。

## 适用性与验收进度

| 验收项 | 本批适用范围与结果 | 命令、退出码和证据 | 限制/剩余工作 |
| --- | --- | --- | --- |
| E0五映射/DDL | 每项值、类型和顺序相同：51固定来源、54维护表、49主表、49表组、52主键；55物理表与维护54表含义保留 | `python build/architecture-e0-20261019/preflight.py` exit0，`preflight.json`；DDL及冻结文件SHA核对 | 最终提交前再核冻结输入 |
| C1/C2 | 精确身份、语义、六类顺序保持 | `scripts/assembly_contract.py snapshot --output build/architecture-e0-20261019/assembly.json` exit0；正式baseline/mapping/order-baseline check exit0 | 公共回归266通过 |
| C3/C4 | 公共→具体业务依赖退役一项；无新增债务 | `scripts/architecture_contract.py check` exit0，333模块/1317导入/51旧债务/0新增/1退役 | 完整发布还会重核 |
| E0反例 | 初轮99通过；补充资源初始化/非法标识/重复列/集合顺序后公共回归266通过（43.47秒） | 初轮`metadata.xml` exit0；最终`pytest tests/test_business_schema_contract.py tests/test_business_schema_metadata.py tests/test_documentation_sources.py tests/test_documentation_review.py tests/test_market_mapping.py tests/test_packaged_runtime.py tests/test_assembly_contract.py tests/test_assembly_order.py tests/test_assembly_source_gate.py tests/test_architecture_contract.py tests/test_ui_architecture.py tests/test_ui_architecture_counterexamples.py --basetemp build/pytest-e0-common-20261019 -q --junitxml build/architecture-e0-20261019/common.xml` exit0 | 无skip；覆盖资源加载实际失败和显式root核对 |
| E0设计/容量 | 55表/49数据集/12 JSON通过；37个measured数据集无实际绑定变化，无需重测旧业务容量 | `scripts/verify_database_design.py` exit0；`preimage.json.capacity`逐项绑定交集为空 | 完整发布仍执行既有隔离quick容量；不是刷新旧报告hash |
| 类型/静态 | 新BusinessSchema结构及全部读者API有严格类型，纳入正式mypy第7文件；全部src/tests/scripts ruff通过 | 最终`python -m mypy` exit0/7文件；显式本模块严格mypy exit0/1文件；ruff exit0 | 首次补查新模块36个未标注错误已修复，未放宽配置；全量门禁待做 |
| R恢复/隔离 | 5项真实隔离集成通过，22.84秒；中断/续跑、切换/回退、同数新业务拒绝回退、额外来源拒绝、实际索引变化和股票证明缺业务拒绝 | 显式`EMPIRE_INTEGRATION=1`及本轮13348配置，`pytest tests/integration/test_business_schema_migration.py --basetemp build/pytest-e0-migration-20261019 -q --junitxml build/architecture-e0-20261019/migration.xml` exit0 | UUID私有库，未迁移生产库；无skip |
| H来源实采 | 不适用本批：无采集器、规范化、网络、消息、业务读写或生命周期变化，映射逐值保持 | 五映射前后等价及DDL不变作为本批替代证据 | D严格来源FAIL仍在，不据此宣称其通过 |
| T3 | 类型补齐后最终完整协议18/18通过；最终输入首轮news_search p95失败保留；此前输入三轮仅作历史 | 原CLI `measure --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output build/architecture-e0-20261019/performance-final2.json` exit0；`compare --report .../performance-final2.json --baseline ... --output .../performance-final2-comparison.json` exit0 | 最终输入`5287ac717081d0d305bc57c37a17691acfce23f30f9bbf1156e86c1941b474ca`；超限根因未确定，未改工具/阈值/系统配置，未删除或合并样本 |
| M文档 | 设计规范、数据库入口和程序内维护说明已同步；JSON进入审阅追踪 | 最后review/check/verify_documentation各exit0；209篇/1470链接/55表 | 用户操作、表/键、页面和任务身份无变化，coverage不新增虚构关联 |
| U1/U2/U3 | 正式E0包实际可见，单页/采集器启停与依赖保护、未保存草稿、滚轮、稳定选择、正常关闭重开通过 | 下文同包桌面与最终只读复核，exit0；真实窗口27921844→正常退出→1708426 | 本批未改变写命令取消或QueryScope，相关自动回归保留；动态快照不代表来源全量完整 |

所有命令从项目根执行，Python为`.venv/Scripts/python.exe`。上表开发时的“待做”说明保留当时语境，最终门禁及桌面事实以下列新证据为准，不能据旧D结果替代。

类型补齐后同组266公共测试再次通过，42.00秒，`final-common.xml`；同组5项真实隔离恢复再次通过，19.26秒，`final-migration.xml`，各exit0、无skip。设计门禁和精确装配再次exit0；架构`final-architecture.json`无新增债务。初始未标注模块的严格mypy检查exit1/36错误，修复注解及明确边界后本模块/正式7文件均exit0，未禁用严格选项。最终[五映射/DDL/容量绑定复核](architecture-e0-final-equivalence-2026-10-19.json)同时检查额外pyproject与全部实际diff，37个measured绑定仍全部当前且无触及。

第一次文档review缺逐功能理由被正式门禁拒绝exit1，未伪造审阅；实际审阅70项关联后用正式review CLI逐项记录不变理由并exit0。设计规范、数据库入口和程序内资源维护章已有真实正文同步；不变表字典/任务/日历页面/Redis仅因公共依赖与追踪扩大而失效，各自理由记录既有值、生命周期、DDL与实现保持。随后check/verify_documentation exit0（209篇/1467链接/55表），四文件文档专项35 passed/26.36秒。类型补齐后最后review重新通过，当前65项失效关联逐项理由，check/verify_documentation再次exit0（209篇/1470链接/55表）；本地review_documents.py实际调用正式CLI，未直接写审阅摘要。

最终性能[首轮失败](architecture-performance-e0-final-failed1-2026-10-19.json)保留news_search p95 20.25124ms超原17.8190125ms，其余17项通过，correctness/cleanup通过；随后[最终完整通过](architecture-performance-e0-final-2026-10-19.json)18项通过，measure/compare各exit0。两次最终输入相同，原始样本全部保留；没有从多轮取最快样本拼接。性能测量只证明固定私有负载，不代表来源吞吐/真实桌面/断电持久性。

机器核对与原始报告：[五映射/冻结/容量/调用方审阅](architecture-e0-equivalence-2026-10-19.json)、[T3第一轮失败](architecture-performance-e0-failed1-2026-10-19.json)、[第二轮失败](architecture-performance-e0-failed2-2026-10-19.json)、[第三轮完整通过](architecture-performance-e0-2026-10-19.json)。本地审阅器`audit_equivalence.py`实际退出0：逐项等价、冻结输入与37项measured当前绑定全部核对；报告不是手写通过。三轮业务输入同为`73b5989eea91885d488168607ec46076e2c2d5ecd023787cdef763d0da7d80b4`，correctness一致、cleanup均true。第一轮holders_detail p95 7.95826ms超6.1948125ms（单次最大16.14ms）；第二轮news_first p95 13.66286ms超9.8252625ms（最大26.7089ms），其余17项各自通过。第二轮未重现第一项超限，不据此声称已消除噪声或定位环境原因；三轮全部原始samples均保留。

## 资源与恢复

本批新核自有13348实际UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、端口及任务datadir匹配；仅四个系统库、无其他客户会话。共享Redis实际Stream本次只读pending0，不启动第二归档器、不改RouterProxy。两份config和原偏好SHA保持并记录在本地preflight；不输出配置正文。21:22后新观察工作台45任务、活动0/pending0，Alt+F4正常关闭D包，随后fresh窗口列表为空；本地`desktop-before-close.json`保存树。性能独占期间未运行测试/扫描/构建，工作结束重开。

不执行生产DDL、数据迁移或删除业务。恢复只涉及本批代码/资源及相匹配程序包，不回退业务表；不存在启动自动迁移或并行读写路径。

## 完整正式发布与最终同包验收

第二轮唯一正式入口 `verify-release.ps1` 在干净HEAD `99e69dba436e52eb890f407371beae6c88938274` 完整退出0。run `8ba4515618874a4dae5fbdaba42d04d7`，publication `committed/passed`，未重复发布。完整源输入 `1ece6878aa782c16fc96e72ad43c5b8d9ee02c6ed47848ef0216242872d0c7ae`；EXE `2eb60f909c09c71109a861203fa9dbca55903e784fe9cb650f5a00e059bc4fd2`；安装树 `a772600880f929710a4bc82b632faa0a3ca12272addcab39228c15ba60683d73`。包内 `_internal/sql/business-schema.json` 与正式资源逐字节相等，SHA `30d38c7b0702ab5d1eb16e650152d59a75cc7a9f00493d0e6b6608700406422d`。

24步骤均按正式预期退出，输出完整；其中step-022为首次缺配置生成模板，预期exit1，随后step-023复查exit0，并非隐藏失败。完整pytest **3660 passed、5 skipped、24 warnings，2216.05秒**。五skip均state-unit显式drill opt-in，不计通过；E0未改该实现。四条入口子进程编码警告以 `PYTHONUTF8=0` 重跑确切参数化测试，4 passed/4.97秒、无警告，`entrypoint-encoding.xml`；其余警告保留原日志。环境、42依赖、文档、设计、架构、精确装配、ruff、mypy7、pip、quick隔离容量、四档DPI、PyInstaller、中文空格目录包/配置smoke与正式切换全部通过。

命令 `.venv/Scripts/python.exe build/architecture-e0-20261019/check_published_runtime.py --run 8ba4515618874a4dae5fbdaba42d04d7 --report build/architecture-e0-20261019/post-release.json` exit0；桌面完成、正常退出后以新输出 `post-desktop-final.json` 再次exit0。后者22:46:16只读全局pending0、服务正常退出，核同包清单/EXE/树、两配置、偏好、从 `C:/Windows` 运行正式EXE doctor真实Redis/MySQL连接、股票/新闻及持有人三种browse/detail和第二页。CLI doctor由正式包执行；查询由源码正式API使用安装配置执行，实际可见页面另由下列正式EXE验证。原报告的 `actual_desktop=pending` 原样保留，不篡改为UI通过。[最终只读报告](architecture-e0-post-release-2026-10-19.json)。

实际桌面通过computer-use技能的 `@oai/sky`，使用返回的正式EXE窗口27921844，逐次观察、单次操作并刷新，保存 `build/architecture-e0-20261019/desktop-*.json` 原始树/截图。不是离屏，也没有用开发源码窗口代替：

- 运行状态可见 `Empire 0.1.0 · 99e69dba436e · 干净提交`、两真实服务连接、自动归档及pending0。帮助“数据库职责与查阅→程序资源与维护”新JSON正文可读，滚动条0→250、章节组合框保持。
- 数据目录按需打开股票5579条/28页/每页200；平安银行选择在刷新后保留。日历实际2026-10月逐日显示交易/休市，不把初始异步空页算通过。
- 财经快讯37175条快照，22:39新闻标题、北京时间和正文实际可见。前十大股东920296.BJ/2026-10-21保留来源日期超前质量提示；流通股东603833.SH/2026-10-14名单、比例可读；债券688605.SH/2026-08-22先锋转债显示实际排名缺口说明，不补造缺失持有人。这些是现有生产记录的页面可用性抽验，不扩张D实采结论。
- 单停 `ui.calendar`，采集管理仍有45任务、巨潮日历任务可用；恢复后日历页面可重新创建。单停 `collector.cninfo_calendar`，任务管理/历史仍可读，日历立即采集正式返回“该采集插件当前未启用”；新闻计划仍完成50条。恢复采集器后核状态已启用。未执行日历实采。
- 对Redis仅点普通停用，正式依赖保护拒绝并列出八项依赖者，Redis仍启用；未点级联。这里操作的是Empire插件，未重启/清空共享Redis服务。
- 原日历计划每天20:30、重试2、代理优先可回退保持。仅把重试改为未保存草稿3；自动刷新、切帮助再返回仍为3，数字与网络组合框真实滚轮均不改值。撤销后回2，保存/撤销按钮禁用，从未保存测试策略。股票刷新选择、帮助正文滚动已另验。
- Alt+F4正常关闭后fresh窗口列表无Empire；随后重新启动同一正式EXE，窗口1708426真实可见，工作台45任务、活动0、pending0、连接正常，原新闻计划继续。四个既有失败任务及来源缺口照常显示，未借本批清错或声明已修复。

插件启停按原Runtime.command写入全部159个当前启用项，原偏好仅10个显式true项，导致首次关闭后 `post-desktop-close.json` exit1拒绝偏好差异，该失败报告保留。先核本轮输入、全部159项true、原10项true及实际保存代码；最初过严键交集断言遇到旧 `infra.scheduler` KeyError，未写文件。保留本轮展开文件后用精确SHA守卫恢复原字节，重新执行最终检查exit0。根/dist配置均始终SHA `5c1e32fdf651b948c387106d2a006ba390b7cb1001827fc537262deae832f92f`；原偏好SHA `8cbc58900b35bf4c8b2f9fff47ed95f67f6e20782734f38a0819ff3c7cadd63e` 恢复且重开后仍相同。未覆盖并发未知输入或更改任何保存任务策略。

最终只读审阅命令 `.venv/Scripts/python.exe build/architecture-e0-20261019/final_audit.py` exit0，[机器审阅报告](architecture-e0-final-evidence-audit-2026-10-19.json)重读24步骤预期退出/完整日志摘要、JUnit逐skip、retained outputs、包资源、最终只读结果、配置/偏好及真实观察文件身份。报告是审阅脚本实际生成，UI结论来自上述实际操作，不把文件存在本身当通过。全部最终实现输入已绑定发布，后续本结案文档提交不冒称被打入旧EXE。

E0适用C/R/T/M/U退出项完成；H因无采集实质变更不适用，D两项严格来源FAIL及既有分红完整容量待解决项不因此消失。E1须在本批文档门禁、提交推送及远程核实后开始。

结案文档最后审阅后，`scripts/documentation_contract.py check` exit0、`scripts/verify_documentation.py` exit0（209篇/1475链接/55表）；四文件文档专项以独立 `build/pytest-e0-close-docs` 执行exit0，**35 passed/28.62秒**，`close-docs.xml`。仅事实文档变化，不重复构建。推送前实际ls-remote仍08fe382，与前批一致。
