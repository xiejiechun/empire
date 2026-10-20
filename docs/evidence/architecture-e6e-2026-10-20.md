# E6e 业绩与股东变动实施记录

当前状态：**本批组织迁移范围已验收，结案提交待推送精确核实**。有限实采与全历史准备分别判断，限制见文末。前批E6d正式发布与真实桌面已验收，结案`1cae32e287b11f3c93b5542390f554d86c30ef4c`已推送main，以共享代理实际ls-remote精确核实。E6f～g/F未实施，整个优化未完成。

## 前像、范围与准入

开工main干净，当前安装E6d `0cc06d1a846f42e78088bfad72ccfcd4`/干净构建7b1fb830。正常Alt+F4观察关闭提示，fresh窗口列表无Empire；关闭前活动0/pending0、既有失败2。`py build/architecture-e6e-20261020/preflight_resource.py <release> <commit>` exit0，自有13348实际UUID a3e8a5eb-cb64-11f1-8ddf-380525361d4e、datadir、仅四系统库/无他客户均核实，生产UUID不同；config/偏好、冻结文件保持。

六旧模块contract、source、collector、dataset、query、ui迁入`features/performance`，全部调用方、脚本、测试、coverage、assembly与ownership同步；原remaining只移走六kind声明，回购和规则保留。逐文件字节前像、映射与实际HEAD在本轮`preimage.json`。六kind为earnings_forecast/quick/disclosure/report、holder_count、shareholder_changes，独立query/collector/UI及任务/数据贡献槽位保持。不改DDL、消息、字段、持久身份、用户策略或来源解析/恢复语义；无兼容转发、双路径或启动迁移。

验收适用性在新实采前登记：本批是组织迁移，按acceptance 6.1要求逐模块AST/契约、身份顺序、输入输出与恢复等价和有限正式E2E；不以AST替代UI行为。仍选择原池种子20261020随机30与已知失败来源单元核查，各自记录严格实采结果。不会将原有来源失败改写为通过，若调查需实质修改则重新登记并执行适用的完整30股准入。两容量绑定随路径失效，必须真实新测，五项业绩各100000行与股东变动100000行原协议/SQL/次数/阈值保持；冻结T3不改。

## 已登记的日常错误

只读doctor两项目均exit2/partial，CLI无法确认当前进程内隔离状态，不能称诊断全部通过。披露时间e4e9879cf40348eb8904bce0765f0ea5（2026-10-20）及919e69f70c8d44149e1594b40db46ed9（2026-10-19）在queue_publish报实际披露或统计日期超过采集时点；没有响应正文。业绩报告f70e85b27f4244d2a1484bec33d2d7bb在2022-03-31来源单元报方案集合与独立总数不符；错误正文仅有界前缀，不能据此重建完整响应。精确ID及原诊断保存在本轮build，未清理；先调查真实来源，不能放宽校验使其变绿。其他旧网络错误未因查看而判修复。

## 验收矩阵

| ID | 状态、实际命令与证据 | 适用范围/剩余工作 |
| --- | --- | --- |
| C1/C2 | `assembly_contract.py check` exit0，原baseline/order与受审mapping | 六kind每项身份、完整顺序一致。首轮工厂未加入导致六kind缺失，检查真实拒绝；已接回工厂，未改门禁 |
| C3/C4 | `architecture_contract.py check --output build/architecture-e6e-20261020/architecture-1.json` exit0；全仓Ruff exit0 | 406模块/1459导入/0新及既有债务/45退役；旧六路径与调用方退役，最终再核 |
| R1～R4/U开发 | `py -m pytest tests/test_tdx_performance.py tests/test_tdx_performance_lifecycle.py tests/test_tdx_performance_ui.py tests/test_tdx_shareholder_changes.py tests/integration/test_tdx_performance_archive.py tests/integration/test_tdx_shareholder_changes_archive.py --basetemp build/pytest-e6e-domain -q --tb=short --junitxml out/domain.xml` exit0 | 135 passed/206.73秒，无skip；独立13348显式配置，每kind解析、NULL/日期、冷热摘要、修订/旧响应、SQL提交后重放和清队、按序预取及整轮确认 |
| R2安全工具 | `py -m pytest tests/test_performance_verification_tools.py tests/test_source_verification.py --basetemp build/pytest-e6e-safety-scoped2 -q --tb=short --junitxml out/safety-scoped2.xml` exit0 | 110 passed/11.39秒，无skip；实际六kind完整schema/DML/模拟HTTP到正式查询，跨库/错实例/多语句、精确超时hint、取消恢复。模拟HTTP不计实采 |
| R2有限来源/旧错误 | `py scripts/verify_tdx_performance.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --seed 20261020 --random-count 30 --proxy-only --timeout 1800 --output out/source-2.json` exit0；[原报告](architecture-e6e-source-2026-10-21.json) | 30随机+3固定、59全代理请求、42943规范行，六kind集合/内容及正式分页一致、pending0和六项cleanup通过；仅声明范围通过，全历史准备结果及用途限制原样保留 |
| 五表容量 | `py scripts/measure_tdx_performance.py --test-settings build/architecture-evolution-20261019/mysql-settings.json --output out/performance-capacity-2.json` exit0；[新实测](architecture-e6e-performance-capacity-2026-10-21.json) | 各100000行/5000证券×20期，逐表全量业务键/内容核对、重复0业务DML及修订1行，原查询五次取最大、全部原预算通过、六清理通过 |
| 股东变动容量 | `py scripts/measure_shareholder_changes.py --test-settings build/architecture-evolution-20261019/mysql-settings.json --output out/changes-capacity-1.json` exit0；[新实测](architecture-e6e-changes-capacity-2026-10-21.json) | 100000事件/5000证券×20月，全量内容核对；200条4.69ms、整月145.06ms、分配81313792字节、导入5.99秒、重复0.287秒/0DML、单行修订0.246秒，原预算及六清理通过 |
| T3 | `py scripts/architecture_benchmark.py measure --protocol docs/evidence/architecture-performance-protocol-2026-10-19.json --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output out/t3-1.json` exit0；[原报告](architecture-e6e-t3-2026-10-21.json) | 原18项全部通过、correctness及cleanup通过、无不可比项；冷声明median1073.76/p951108.57ms，原阈值1267.91/1305.99ms；测前其他测试结束、CPU抽样无持续重负载，未修改冻结工具/协议/基线 |
| M/A/U1～U3 | M文档与逐kind不变说明通过；唯一正式门禁exit0、3835 passed/5原opt-in skipped；[同包真实桌面](architecture-e6e-desktop-2026-10-21.md)完成 | 六页/筛选分页/帮助/独立启停与依赖保护/草稿/滚轮/982窄窗/原设置和正常关开均有原观察；结案push精确核实后才进入E6f |

历史H3空名债券、E4严格来源FAIL、资本历史准备限制和停复牌精确错误保持。必要证据缺失时不得进入E6f。

## 2026-10-21验证事实与限制

上表`py`为`.venv/Scripts/python.exe`，`out`为`build/architecture-e6e-20261020`；领域和安全测试显式`EMPIRE_INTEGRATION=1`、`EMPIRE_TEST_MYSQL_SETTINGS`指向已核13348配置。凭据及ownership原文不提交。正式来源输入`625b96e97442af8d0612e4080f0125f358e6b5177cb4b3590eadf8bb8d0fa384`；两容量的精确bindings与当前文件逐一核实，容量后仅更新本批无关用户说明，未改测量实现或绑定。两份报告为真实新测，六设计卡已引用；旧报告不改hash。历史真实规范行仅作为明确的固定放大fixture，容量不冒充本轮来源或生产覆盖。

六旧模块去import并按受审映射规范化后AST逐项相等，逐字节前像、映射和比较见`out/preimage.json`、`organization-equivalence.json`。新bundle接回原六类槽位，实际assembly比较身份/语义/顺序通过；Ruff全仓与strict mypy八文件exit0。公共平台、preparation契约、任务/数据集/schema/page身份与原用户策略未改，不以AST替代最终实际桌面。

新安全工具复用原`PrivateStorage/source_verification`生命周期。`performance_storage.py`仅对原审计固定`MAX_EXECUTION_TIME(15000)`提示做语法适配，再经基类实际server_uuid、当前库和全语句检查；源命令在单进程范围内替换并恢复资源工厂，容量继承该适配。没有修改共享守卫或新增资源清理系统。原生产实采/保存默认策略的同名股东变动脚本已退役，程序内说明同步去除旧`--start/--end`生产写入示例，改为显式私有核验及恢复入口。

首实采[原失败报告](architecture-e6e-source-first-2026-10-21.json) exit1，59全代理，固定2022-03-31报告实得4747、独立总数4746；其他有效范围经正式链路，pending0/六清理通过。该轮preparation被工具守卫拒绝，不能当业务准备验收。第二轮同种子同固定范围，未改来源解析/总数校验，源响应变为4746/4746（正文摘要84026a5c3eedea94955c1afaec7172e8bce03f0d73a465f0d04d874e532d272e），固定反例成功是来源变化，不是程序修复；生产错误ID未清理，第一轮FAIL保留。

第二轮四报告为2013-12-31、2022-03-31、2026-06-30、2026-09-30及各自最新期（预告另含2026-12-31），股东变动为1990-01/2010-01/2014-06/2026-09，户数为冻结33证券全部可得历史。分别4398/2473/18045/13370/1189/3468规范行；33/12等单元与每证券空集语义见报告。有限范围不满足全历史manifest，四报告和变动默认全历史准备仍失败；预告空正文与2014-06来源未知数量仍保留，户数统计日不作为公告日。采集完整与分析可用明确分开。

安全首轮fixture未初始化完整schema：1 failed/108 passed；修fixture后109 passed；最后命令单文件11 passed。扩展hint回归首轮断言误把正常说明中的SQL文字当错误：1 failed/109 passed，改为核实实际守卫错误后110 passed。原JUnit都保留。首容量[失败报告](architecture-e6e-performance-capacity-failed-2026-10-21.json) exit1：元数据绑定参数名table触发守卫，改为t且SQL内容/原协议不变；六清理均通过。首公共回归命令把两个集成文件误列为tests根，exit4/未运行；改为实际integration路径后重跑，失败日志保留。

公共回归实际命令为`py -m pytest tests/test_feature_bundles.py tests/test_assembly_contract.py tests/test_assembly_order.py tests/test_assembly_source_gate.py tests/test_dataset_contributions.py tests/test_manager.py tests/test_architecture_contract.py tests/test_collection_control.py tests/test_unit_prefetch.py tests/test_prefetch_budget.py tests/integration/test_live_pipeline.py tests/integration/test_prefetch_pipeline.py tests/integration/test_archive_fairness.py tests/test_incomplete_response.py tests/test_http_response_safety.py tests/test_ingest_reservations.py tests/test_performance_verification_tools.py tests/test_source_verification.py --basetemp build/pytest-e6e-public2 -q --tb=short --junitxml out/public2.xml`，显式独立集成环境，exit0、405 passed/177.28秒。

最终实际CLI `scripts/documentation_contract.py review --note <本批六kind与安全入口具体审阅说明>`，为五个未变数据页及shareholder_change表分别记录`--unchanged FEATURE=具体理由`；不以全局理由代替逐功能审阅。`documentation_contract.py check`、`verify_documentation.py`、`verify_database_design.py`均exit0（253文档/1749链接、55表/49数据集/12JSON）。文档回归`py -m pytest tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py tests/test_storage_help.py --basetemp build/pytest-e6e-docs2 -q --tb=short --junitxml out/docs2.xml` exit0，35 passed/26.18秒；首命令误加不存在的第五文件exit4、未运行，日志保留。

正式发布前源身份与source-2精确匹配、两容量bindings逐文件相同、T3源/冻结文件保持已核。48条SQL保存设置payload/updated_at与E6d原快照相同，两config及原偏好逐字节相同。待形成干净实现提交后运行唯一正式门禁；正式发布与同包真实桌面仍未完成，不能进入E6f。

实现提交`3fc70828f5bcd01dfe6be887ff6acaf9c4793c4a`首轮完整发布`da0a53aa761f4fb9a1278da12666b07b`在第3步文档检查失败：最后review后继续更新状态和验收文档使content摘要过期。环境与42项依赖检查通过，未进入pytest/打包/切换，原E6d安装保持。原日志`out/release-1.log`、本轮inputs/steps/failure.json保留，该轮尚无publication journal。修复为文档定稿后重新执行同一review CLI、check、文档回归并形成新干净提交，再从头执行唯一完整发布；不改文档门禁或拼接失败轮证据。第一次修复后同四文件文档回归`--basetemp build/pytest-e6e-docs3 --junitxml out/docs3.xml` exit0，35 passed/26.93秒。

## 正式发布与桌面出口

最终文档回归docs4为35 passed/26.60秒，形成干净提交`5bcffb7ce31561a44070dfc6998fe5cc87ce6e25`后执行唯一`.\verify-release.ps1`，完整exit0。release `455c9c6d9c33438a9022dfa863cd1ff1` committed/passed，24步骤/1743输入/54保留输出逐项审计通过；3835 passed、5原state-unit opt-in skipped、20 warnings、2507.41秒。source/EXE/tree身份、逐项skip及原证据见[发布审计](architecture-e6e-release-audit-2026-10-21.json)。未修改冻结工具/协议/基线/阈值，发布期间HEAD和保护输入保持。

[同包真实桌面结案](architecture-e6e-desktop-2026-10-21.md)逐项覆盖U1～U3及实际限制；105条原观察、三份成功只读报告、两份失败及导出摘要均保留。原config、48保存设置和最终原偏好保持；正式包正常退出后重开1316790，工作台实际可见、45任务/pending0。只读首轮未来日期选择与关后偏好展开失败保留，修核验条件/恢复验收偏好后实际重跑，不改正式实现。纯结案文档不改变已安装包身份；文档定稿后重审与相关回归，提交并push精确核实后进入E6f。
