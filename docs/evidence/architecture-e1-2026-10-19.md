# E1 财报三表：实施与验收记录

状态：开发验证通过，尚未正式发布及真实桌面验收；不得进入 E2。前批 E0 结案提交 `953a34e8dc8895dd98a6a4461df212ea599c1ffc` 已推送，开工工作区干净。首次复核 GitHub 连接失败，随后 ls-remote exit0，main 精确匹配该提交。上个安装包仍是 E0 release `8ba4515618874a4dae5fbdaba42d04d7`，未把开发代码当安装结果。

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
