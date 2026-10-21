# E6g 交易规则归组实施记录

状态：开发验证通过，尚未发布/桌面验收，F未开始。前批E6f结案提交0d7b2fe9d93c336aa17cea6e0e0c665ebd194c12已推送且ls-remote精确匹配；不是重做前批验收。

## 输入、范围及身份

本轮从干净main/0d7b2fe开始，out为build/architecture-e6g-20261021。开工只读核实原发布7f5acbb5的committed/passed及EXE摘要、两config/偏好、正式实例与独立13348的实际UUID/datadir；测试实例仅四系统库且无其他客户会话，生产UUID不同，全局pending0。未清共享Redis、不停数据库、不清生产错误。Empire17699188经Alt+F4正常关闭，显示保存进度/结束归档/关闭连接后，fresh窗口列表无Empire；工作结束须重开。

11模块按实际正式前像迁到features/trading_rules：contract/review/bse_review、collector/sources/parameters/documents/bse、dataset/query/ui。旧contracts及plugins下对应实现已删除，无转发兼容。所有调用方、测试patch、规则source_file、coverage、assembly和architecture归属同步。全部11模块去导入AST相同，字段、异常、请求、分页、恢复、版本与规则解释保持，见[等价](architecture-e6g-organization-equivalence-2026-10-21.json)、[前像](architecture-e6g-preimage-2026-10-21.json)。

remaining当前只含规则，原插件3800～5900、任务1200～1800、数据集1200～1800槽位原值移入bundle，规则七kind及plugin/task/job/dataset/schema/page身份保持。builtin只增规则工厂并移除remaining入口；旧remaining已退役，未清空其他未迁业务。公共preparation保持原路径，下载/代理/频控/预取/入队/归档/摘要/SQL调度不复制，不DDL、不双写、不启动迁移。

## 验收矩阵与命令

所有py指项目.venv/Scripts/python.exe；实际命令在项目根执行，集成显式EMPIRE_INTEGRATION=1、EMPIRE_TEST_MYSQL_SETTINGS=build/architecture-evolution-20261019/mysql-settings.json。下表记录开发阶段事实，正式发布及桌面须另补真实结果。

| ID | 适用范围/结果 | 实际命令及证据 |
| --- | --- | --- |
| C1/C2 | 身份、语义、顺序与唯一贡献归属，通过 | py scripts/assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json，exit0；snapshot --output out/assembly.json，exit0 |
| C3/C4 | 旧实现与remaining退役，架构通过 | py scripts/architecture_contract.py check --output out/architecture-2.json，exit0，409模块/1463导入/0债务/45已退役；11模块AST同一 |
| R1～R4 | 七kind原协议、类型/单位/日期/NULL、源解析、热冷摘要/零DML、引用修订/旧响应/SQL后重放与清队，原领域62项通过；首轮新工具失败已修复 | py -m pytest tests/test_trading_rules.py tests/test_rule_documents.py tests/integration/test_rule_archive.py tests/test_trading_rule_verification_tools.py --basetemp build/pytest-e6g-domain --junitxml out/domain.xml -q，exit1，62 passed/1 failed/141.09秒；失败是新工具启动依赖次序，非原业务通过证据失效 |
| R2工具安全 | 修正后128项通过 | py -m pytest tests/test_trading_rule_verification_tools.py tests/test_source_verification.py tests/test_capacity_session.py --basetemp build/pytest-e6g-safety --junitxml out/safety.xml -q，exit0/128 passed/11.58秒；真实私有SQL七kind管线、错实例/跨库/SQL注入、取消恢复与清理 |
| 静态/类型 | 通过 | py -m ruff check src scripts tests，exit0（首轮7个导入排序问题，定向自动排序后通过）；py -m mypy，exit0/原strict八文件，无扩阈值 |
| R来源 | 第一轮全七kind/77参数，15全代理/0直连，完整参数与引用/市场筛选/分页/SQL一致，pending0/六清理通过 | py scripts/collect_trading_rules.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --proxy-only --output out/source-1.json --timeout 1200，exit0；最终源码核验另列，不把后续工具修订冒称相同全源摘要 |
| E6g容量 | 原77参数加10000压力行真实新测量通过，七卡引用已更新 | py scripts/measure_trading_rules.py --test-settings build/architecture-evolution-20261019/mysql-settings.json --output out/capacity-2.json，exit0，见[容量](architecture-e6g-capacity-2026-10-21.json) |
| 数据库设计 | 55表/49数据集/12JSON，当前通过 | py scripts/verify_database_design.py，exit0；[绑定失效扫描](architecture-e6g-capacity-binding-scan-before-2026-10-21.json)仅七张规则设计卡共用报告失效，已真实重测 |
| R公共/U架构 | 318 passed/139.15秒，exit0 | 既定装配/架构/管理器/任务控制/公共下载及入队/预取/归档公平/live pipeline回归；out/public.xml |
| T3 | 首轮完整18/18通过，exit0，正确性/cleanup通过，无不可比项 | py scripts/architecture_benchmark.py measure --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output out/t3-1.json；[原报告](architecture-e6g-t3-2026-10-21.json) |
| M文档 | 正文/coverage同步，具体review与check均exit0，verify_documentation exit0/259文/1804链接/55表；41文档专项exit0/26.95秒 | 规则操作/限制、SQL归属、架构、包README；无关业务的行为不变理由逐项审阅 |
| A1～A3 | 冻结保护未改，无新增破坏性演练 | 完整门禁仍须执行发布反例，不能借开工核实标发布通过 |
| A4/U1～U3 | 未发布待后续 | 同包配置/连接/全部七query与可见页、独立启停/依赖保护/草稿/滚轮/窄窗/正常关开仍须完成 |
| F/M1/类型扩展/成本实验 | 未开始 | E6g未结案前不实施F |

## 真实来源适用范围

本批11模块为纯组织迁移，来源与业务行为不变。来源以官方法规/通知/附件及税费文档组为单位，没有按股票筛选的请求接口；随机30股票不适用，不宣称满足30股。替代验收为七kind全部来源参数、条款引用、规范消息、SQL及正式查询的集合与每列内容，全部市场及引用详情逐项比较，且pending0；不会用总数77代替完整集合。

首轮各kind参数/引用数：limit14/8、settlement5/3、lot14/6、tick5/3、sessions23/5、stamp4/4、transfer12/1。五交易所输出复用原一分钟已解析缓存；共15次代理请求，观测与重新解码不新增来源请求，不长期保存成功响应全文。来源URLs、字节数及摘要保留，私有资源归属token不导出。

只核验当前已审核文件范围。沪深T+1数值、科创板递增数量、北交所涨跌价格舍入、现行完整过户费表及最低收费仍缺，准备失败保留。过户费引用新华社转述2022公告，不能改成现行中国结算完整表已通过；北交所43号公告的大宗报价生效日期不影响普通竞价，不启用暂缓盘后条款。原H3空名债券/E4严格来源/历史准备限制保留。

## 容量与工具边界

旧同名collect会修改正式任务计划，现已替换为共享source_verification/PrivateStorage生命周期：只读正式配置/必要身份，实际server_uuid、UUID SQL与Redis归属、同连接锁、SQL会话守卫、取消/清理和新报告，不写生产业务/任务/站点。七输出独立核对；没有第二归档器/代理下载实现。

新容量保留旧77审核参数和10000未来历史压力行、原查询、20次采样P95索引18、全部原预算；完整参数/引用内容核对、重复零业务DML、单参数有效修订1行、压力10000行内容一致。实际import0.137254秒、page P95 2.079700ms、detail0.539800ms、coverage23.079000ms、分配12763136字节，均低于原5秒/200ms/200ms/500ms/64MiB。合成压力不是历史或生产覆盖，SQL后清队语义由领域集成及真实来源证明。

## 失败、资源与恢复

首次assembly登记了三项不出现在runtime绑定的解析模块映射而exit1；已移除多余映射，纯解析迁移仍由AST及导入路径证明，不放宽装配检查。首次领域新工具在ingest发布者启动前取能力失败；改为先启动首规则collector（原依赖声明自动启动发布者），安全128项随后通过。

首次容量exit1为CLI找不到tests样本包，未完成测量，六清理true/无残留；保留[失败报告](architecture-e6g-capacity-first-failed-2026-10-21.json)。恢复旧协议要求的根路径后第二轮exit0；不刷新旧报告hash。探索中不存在的猜测路径/PowerShell wildcard rg读取失败、一次apply_patch重复路径拒绝均无业务副作用，忽略账本已记；不可作为通过证据。

自有13348继续运行供本轮，生产MySQL和共享Redis未停未清。旧生产错误未处理亦未清。任何上下文恢复先核out/ACTIVE-HANDOFF.md和真实资源；未完成不能改为已验收，工作结束重新打开正式桌面。

当前源码第二轮来源命令同首轮，仅新输出out/source-2.json，exit0，15全代理、七kind参数/引用与全部正式查询一致、pending0，六清理true。见[最终来源](architecture-e6g-source-2026-10-21.json)，[首轮](architecture-e6g-source-first-2026-10-21.json)保留。两轮间仅容量CLI恢复测试样本导入路径，正式11业务模块/来源解释无变化；未把首轮全源摘要假装改后摘要。

最终17份现行measured报告绑定均有效；当前source2与T3分别按各自工具的不同源摘要范围重新核对有效，不能混用两种hash。一次额外审计错误假设二者摘要同范围导致assert失败，无数据操作；改为各自正式摘要函数核对通过。T3前10秒实际CPU快照未见测试/构建主导负载，并实核无活动pytest/PyInstaller/T3/实采命令和Empire线程；整轮原18项通过，工具/协议/阈值/历史基线/release_lock未改。文档最终审阅采用documentation_contract.py review --note <七规则逐项说明> --unchanged-reason <11模块AST/身份及其他业务与公共路径不变的具体依据>；check、verify_documentation及41文档/规则专项均exit0，最后定稿后再审阅。
