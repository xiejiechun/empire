# E1 财报三表：实施与验收记录

状态：已验收；结案证据随本提交交付，推送核实后进入E2。2026-10-20 完整门禁退出0，同包只读、真实桌面及正常关开完成；本批最终事实见文末。前批 E0 结案提交 `953a34e8dc8895dd98a6a4461df212ea599c1ffc` 已推送，开工工作区干净。首次复核 GitHub 连接失败，随后 ls-remote exit0，main 精确匹配该提交。开工安装包为 E0 release `8ba4515618874a4dae5fbdaba42d04d7`，没有把开发代码当安装结果。

## 范围、前像与正式路径

十模块从 plugins 迁到 features/financial_statements，职责为 collector、contract、dataset、quality、wire、query、audit、ui、statement_matrix、statement_preview。布局资源 statement_layouts.json 同包迁移且字节相同。chain 函数体从采集器移到公开 contract，audit 不再反向导入执行器。新增 bundle、README，由 builtin 显式装配；remaining 仅退役三表声明。

调用方包括源码、规则登记、测试导入/patch/动态预取定位、Empire.spec、coverage、架构归属与装配映射。正式装配映射只登记四个实际贡献模块，十模块完整退役表见[等价报告](architecture-e1-equivalence-2026-10-19.json)。无转发、双注册或第二读写路径。插件槽13800～14600、任务3500/3600/3700、数据集3600/3700/3800保持原值；三个kind、任务ID、dataset/job/project、schema 2、页面ID及用户保存配置不变。

不改 DDL、SQL字段、消息、摘要算法、正常请求次数、来源日期/金额/缺值、默认设置、按序入队、整轮确认或 Redis 丢失恢复。十模块剔除导入后的定义 AST 与真实前像逐项相同；chain 单独逐定义相同，资源字节相同。这是组织等价证据，另有实际SQL/来源与行为回归，不仅凭AST判通过。公共 preparation 路径保留。

安全财报实采入口为本批实质修改的维护工具：删除旧生产MySQL假source写入及猜测清理，复用 D 的 source_verification/source_test_storage。强制显式私有13348、随机至少30、仅代理、固定反例；核实际不同server_uuid、UUID库/namespace、owner、SQL守卫、单实例、取消及清理，正式 source 保持ths。观察器不替换正式写入，先比较规范来源和入队内容，再核正式查询、质量、SQL单元证明和manifest。报告持久落盘、清理及输入复核后才可通过；ownership秘密只留本地。

## 实际命令与结果

所有命令使用项目 `.venv/Scripts/python.exe`。完整原始输出及独立basetemp在 `build/architecture-e1-20261019/`，测试计数有交集，不相加冒充独立用例。脱敏机器记录见[开发审阅](architecture-e1-development-2026-10-19.json)。

| 验收ID/范围 | 实际命令或测试输入 | 退出码、证据与结果 |
| --- | --- | --- |
| C1/C2 身份及六类顺序 | `scripts/assembly_contract.py snapshot --output build/architecture-e1-20261019/assembly-before.json`；`check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json` | 均0；精确身份、语义、映射及顺序通过 |
| C3/C4 职责/退役 | `scripts/architecture_contract.py check --output build/architecture-e1-20261019/architecture-initial.json`；本轮 check_equivalence.py | 均0；335模块、1321导入、50现存债务、0新增、1退役；10模块定义及资源等价 |
| E1/R2/R3、领域/UI/预取 | `-m pytest tests/test_ths_statements.py tests/test_verify_ths_statements.py tests/test_source_verification.py tests/test_all_collector_prefetch.py tests/test_preparation_research.py tests/test_preview_polish.py tests/test_preview_redesign.py --basetemp build/pytest-e1-domain --junitxml build/architecture-e1-20261019/domain.xml -q` | 0，239 passed/2.35秒；补充观察器前的一轮，最终新反例另跑 |
| C/R 公共及安全 | assembly_contract/order/source_gate、architecture_contract、ui_architecture/counterexamples、verify_ths_statements、source_verification 八文件，`--basetemp build/pytest-e1-common --junitxml build/architecture-e1-20261019/common.xml -q` | 0，187 passed/21.29秒；最终完整门禁仍待执行 |
| E1安全工具与取消/清理反例 | `-m pytest tests/test_verify_ths_statements.py tests/test_source_verification.py --basetemp build/pytest-e1-verifier-final --junitxml build/architecture-e1-20261019/verifier-final.xml -q` | 0，103 passed/1.34秒；同实例、跨库/USE/多语句、owner/清理/输入漂移、取消、随机/代理前置、DeferredResponse所有权、同数异内容入队拒绝 |
| E1/R1/R2/R4 隔离归档恢复 | 显式 `EMPIRE_INTEGRATION=1`、`EMPIRE_TEST_MYSQL_SETTINGS` 指向已核私有JSON；`-m pytest tests/integration/test_financial_archive.py --basetemp build/pytest-e1-sql-final --junitxml build/architecture-e1-20261019/sql-final.xml -q` | 0，54 passed/167.48秒；三表分别覆盖来源→查询、冷热摘要、不变零业务DML、修订/迟到、补齐、SQL失败留队、提交后重放、池变化/断点丢失、后续入队不等逐单元归档、范围准备 |
| 安全SQL正向 | `build/architecture-e1-20261019/smoke_guarded_financial.py` | 0；合成来源、真实初始化/守卫/Redis/统一归档/三表query与audit/清理；source_requests=0，不作实采 |
| 静态/类型 | `-m ruff check src scripts tests`；`-m mypy`；`scripts/verify_database_design.py` | 均0；严格7文件通过，55表/49数据集/12JSON契约通过 |
| T3 原冻结协议 | `scripts/architecture_benchmark.py measure --protocol docs/evidence/architecture-performance-protocol-2026-10-19.json --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output build/architecture-e1-20261019/performance-01.json` | 0；[本轮报告](architecture-e1-performance-2026-10-19.json)九指标median/p95共18项、correctness及cleanup通过；无同期Empire/测试/实采/构建，未改工具/阈值/基线 |

前置失败如实保留：本地应用器首次因CRLF匹配失败在写入前拒绝；初始装配映射误含不参与声明的六个模块，exit1后改为四个实际模块；首条SQL测试命令误指不存在的test_source_storage_sql.py，exit4且未运行测试，随后上表54项真实执行。初次ruff六处导入顺序失败，修复后完整通过。没有把失败或缺路径当通过。

## E1 实际来源：随机30加固定10

两轮命令均为 `scripts/verify_ths_statements.py --pool-config config.toml --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --random-count 30 --seed 20261019 --proxy-only --timeout 1800 --output build/architecture-e1-20261019/financial-source-0N.json`，输出分别01/02，新报告不覆盖。两轮抽样完整相同，5579池、30随机、10固定合计40只，三表分别全量历史核验。池摘要/种子/算法/名单、每证券期间集合/内容/质量比较、入队断点、manifest、清理及报告hash见[来源证据](architecture-e1-source-2026-10-19.json)。没有换样或删证券。

首轮exit1：income2635份、balance2555份均40只/40代理请求及pending0；cashflow在固定600644.SH发生502（原共享有限重试耗尽），仅9单元入队，不伪造整轮通过。关闭、SQL/Redis/锁/连接清理均成功，无残留。

第二轮exit0：income2635份、balance2555份、cashflow2560份，三表各40代理请求、0直连/回退，各41个正式入队单元（含manifest）、正式查询逐证券日期集合及规范内容/质量一致，audit集合/manifest完整、pending0。sample_30_met=true来自真实工具结果，全部资源清理通过，不表示生产全市场采完。

来源限制保留：income8条核心金额缺值；balance2条缺值与4条金额质量问题；cashflow242条缺值与6条金额质量问题。质量由当前内容计算，未补零、换科目或删除报告。三表均缺公告日期，不能以报告期代替公布日；历史信号时点失败，普通分析仍受上述金额缺口约束。此处只通过完整采集及组织迁移范围，不宣称全样本估值可用。既有持有人空名债券严格H3 FAIL不变。

## 容量、文档、资源与剩余出口

按实际设计卡审计全部37个measured数据集：每项绑定文件当前字节和旧报告一致，无失效绑定；未刷新旧hash。三表仍为既定legacy_baseline，本轮不改主体存储布局，不宣称做过财报新容量测量。冻结DDL、协议、工具、阈值和历史基线逐hash保持；公共quick容量仍由完整发布执行。分红完整容量未完成，留E5处理。

已同步业务README、来源说明、架构、程序内财报存储与断点主题、三表对象读写路径、规则来源路径及coverage；任务和页面操作保持。首次review因三页面正文未变而拒绝，后按三页分别记录具体无行为变化理由（定义/布局等价、500期上限、累计/时点口径、筛选/空值/质量/可用日期不变），维护工具正文已更新。review/check及verify_documentation均exit0，211篇/1484链接/55表；四文件文档专项35 passed/25.23秒。

最终diff检查发现验证器末尾两个多余空行，修正后diff --check exit0；安全103项以post-whitespace目录重跑exit0/1.41秒。为绑定最终源码，第三轮用同池/种子/固定名单重新完整实采exit0，三表仍2635/2555/2560份、每表40代理请求、pending0，全部清理成功。第二轮报告保持原样；[最终来源证据](architecture-e1-source-final-2026-10-19.json)与[最终开发审阅](architecture-e1-development-final-2026-10-19.json)记录新输入及实际结果。仅末尾空白变化不影响T3的src/sql输入，原性能证据仍精确匹配。最终再次review/check后冻结提交，完整发布及U1～U3尚待下一步，不提前填写通过。

私有13348 UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`，数据目录build/architecture-evolution-20261019/mysql-data；开工只4系统库、无其他客户会话，生产UUID不同。共享pending0的开工观测与实采私有pending0是不同范围。原E0窗口1708426在工作台活动0/pending0后Alt+F4正常关闭，再观察无Empire窗口。生产3307与Redis未重启；两config/偏好摘要开工保留。后续发布保持源码与HEAD冻结，工作结束重开正式可见桌面。

E1当前缺正式发布、同包配置/真实连接/正式查询/三页面/启停/草稿与正常关开，以及结案提交推送核远程；E2～F未开始实施，不以本记录宣称整个优化完成。

暂存检查随后发现新增验证器测试文件也带末尾空行；仅去除末尾空白，全部暂存diff检查exit0。为使完整src/tests/scripts输入摘要精确一致，第四轮同名单真实实采再次exit0、三表各40代理/pending0/清理成功，最终输入记录在[最终冻结来源](architecture-e1-source-final2-2026-10-19.json)和[最终冻结开发审阅](architecture-e1-development-final2-2026-10-19.json)。前三轮报告均保留，不复用失败轮拼装成功。前三轮后未改变来源或业务语义。

## 2026-10-20 正式发布与桌面验收过程

唯一正式命令为显式私有测试配置环境下的 `./verify-release.ps1`，release `7ad607fa635c4f36b662b324dc501e52`，冻结干净提交 `a228421fa7bb312ed9fa0d7aaa0960eb2732c487`。完整门禁退出0、journal committed/passed；pytest **3669 passed、5 skipped、20 warnings，2566.65秒**。五项跳过均为 `test_state_unit_isolated.py` 的显式opt-in演练，不计入通过，本批未改该状态协议。容量quick、四档DPI、PyInstaller、包声明与中文空格搬移/配置smoke和最终切换均完成。24步输出完整；第22步首次生成配置模板预期退出1，其余退出0。没有在pytest结束时提前解冻。

完整输入SHA-256 `f988c9bfd8e9770c455d1e6f12adfa2251a24389ffa0bd9024ecb0a12d9796e6`，EXE `40860a815a7553ad05e7a8a0551ca52b168bfcd4c129756571cfbe2808ec629b`，安装树 `0bc87e56b53c1d13de6650ec3f706f7aa5985433eefea046dac320a26df9bdcd`。本地 `release-evidence-audit.json` 在追加结案事实文档前真实重核1418输入、54份retained输出及JUnit/步骤；所有摘要一致。此后仅事实文档变化不冒称重新发布。

00:11 本地 `check_published_runtime.py --run 7ad607fa635c4f36b662b324dc501e52 --report build/architecture-e1-20261019/post-release.json` 退出0：journal/包内清单/布局资源/EXE/安装树一致，两份config及原插件偏好精确保留；在 `C:/Windows` 执行正式EXE doctor，Redis/MySQL均真实连接。用安装配置启动源码正式query API，三表各核两页证券与前两证券完整日期/内容/质量及列表前5条，股票/新闻正式查询和服务关闭通过、观测pending0。这一API调用明确不是EXE内部查询；下列真实桌面另证同包UI路径。

真实正式窗口5573372显示 `Empire 0.1.0 · a228421fa7bb · 干净提交`。三表实际加载920000.BJ安徽凤凰：利润41期/0需核查、资产负债38期/0需核查、现金流41期/1需核查且2023-03-31警告保留；报告期、科目、万元金额与累计/时点说明可见。利润表按年度切换有效，金额单位滚轮仍为万元且页面正常滚动。帮助搜索“财报 存储”实际显示本批新路径和私有实采安全/清理/用途限制。

U1进行中：实际单停现金流UI，其他财报UI与三采集器仍启用；再单停现金流采集器，任务控制和运行历史仍可读，点击继续采集实际拒绝“该采集插件当前未启用”，未启动实采。U2已观察草稿43200→43201不保存，滚轮及切运行历史再返回后仍43201；尚需撤销该草稿、恢复两个插件和核共享依赖保护。撤销时自动化因遮挡/人工输入拒绝，草稿仍未保存；已暂停鼠标操作并询问桌面空闲窗口，继续独立证据审阅。正常关闭/重开、最终偏好/配置/查询复核、正式证据结案和推送尚未完成，不能据本段标已验收。

## 最终桌面收尾、逐项结论与交付边界

00:31～00:35继续通过 computer-use 的 `@oai/sky` 操作同一正式EXE。用户明确确认暂不操作后，重新观察并激活Empire，点击可见“撤销修改”，43201恢复43200，界面显示“已撤销未保存修改”，保存和撤销按钮均禁用。未点击保存计划。现金流collector随后在插件管理正常启用，刷新后显示已启用。基础服务分类选择Redis，点击普通“停用插件”，实际拒绝 `Stop dependent plugins first` 并列出采集记录、代理、下载、HTTP、入队、归档、确认及控制器依赖；Redis仍启用，没有点击连带停用。

接着Alt+F4正常关闭窗口5573372，随后fresh `list_windows()`无Empire窗口，进程枚举无Empire，没有强杀或删锁。关闭后的偏好确为当前159个正式插件精确集合，除本轮仍未恢复的 `ui.cashflow=false` 外全部true，现金流collector已true；与原10项稀疏偏好共同字段全相同，原有历史键infra.scheduler保留。先保存展开副本，再由本地 `restore_desktop_preferences.py` 以实际SHA守卫（177761cc…）恢复原字节，退出0；恢复SHA为8cbc5890…，未覆盖未知并发变化。该操作同时恢复现金流UI，不改任务、网络或SQL配置。

00:33执行 `check_published_runtime.py --run 7ad607fa635c4f36b662b324dc501e52 --report build/architecture-e1-20261019/post-desktop-final.json` 退出0。同包清单/EXE/树/布局资源、两config及原偏好精确保留、C:/Windows下正式EXE doctor两连接、三表分页及完整日期/内容/质量、股票/新闻查询和服务正常退出均通过，观测pending0。原报告actual_desktop=pending保持原值；[只读证据](architecture-e1-post-release-2026-10-19.json)与真实桌面事实分别记录。

重新启动同一正式EXE获得窗口16058676。工作台可见本地服务已连接、45任务/活动0/待归档0/既有4失败；数据目录现金流页重新打开并完成真实查询，920000.BJ仍41期/1需核查，经营1852.97、投资-6386.49、筹资-957.79万元，恢复成功。利润和资产负债页此前已实际核，未被本轮单停；三页正式查询和身份已由同包UI及只读API分别覆盖。最后返回工作台保持可见，启动后偏好SHA仍为原值。正常日常新闻任务继续使用原计划，不以该快照声称全源数据完整。

| 适用验收 | 最终结论、证据与限制 |
| --- | --- |
| C1～C4 | 精确贡献身份/六类顺序、公开chain、十旧模块及资源退役通过；等价/架构/装配与完整门禁证据见前文 |
| R1～R4 | 三表54项真实隔离SQL恢复及完整发布通过；未改state-unit协议，5项opt-in跳过不计通过 |
| H1～H3财报适用范围 | 最终第四轮同池30随机+10固定、各表40代理/0直连，逐证券集合/内容/质量/manifest一致、pending0和全部清理；金额及公告日期用途限制保留；不替代D严格H3空名债券失败 |
| T3/容量 | 原冻结18项通过；全部37份measured绑定未变化，不伪造新容量；三表legacy_baseline不升级为新容量结论；E5分红完整容量仍待完成 |
| A4/U1/U2/U3 | 唯一完整发布、同包三页/帮助、单页与采集启停边界、共享依赖拒绝、草稿切页/滚轮/撤销、配置偏好及计划身份、正常关闭和重开完成 |
| 文档/远程 | 最终事实更新后重新执行文档review/check及35相关回归；结案提交和实际push/ls-remote另在Git交付记录确认，不改变已发布包身份 |

本地 `final_audit.py` 退出0，重新核全部retained输出、同包身份、只读报告、原偏好及重开观察；[最终审阅报告](architecture-e1-final-evidence-audit-2026-10-19.json)绑定原24步/3669 passed和5 skipped、1418输入初始核对及后续两份事实文档差异。正式发布冻结期间未修改输入或HEAD。00:36直接有界ls-remote退出0，远程仍精确953a34e，尚无他人推进；本轮结案提交推送后才开始E2。整个优化未完成，E2～F仍未实施。

最终事实文档审阅命令 `scripts/documentation_contract.py review --note <E1同包启停/草稿/恢复及用途限制的具体说明>` 退出0；`check` 与 `verify_documentation.py` 均退出0（211篇/1491链接/55表）；四文件文档回归以 `build/pytest-e1-closure-docs`、`closure-docs.xml` 执行，退出0、35 passed/31.33秒。没有重跑已成功正式发布或改变运行包。
