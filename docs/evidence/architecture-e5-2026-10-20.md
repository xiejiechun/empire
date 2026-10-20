# E5 资本事件与复权实施记录

状态：**已验收（组织迁移范围）**。正式实现e403faa已完成唯一发布056304060b0249828b21ac2b8fafa092；3770 passed/5 opt-in skipped。同包真实连接、正式查询、配置与48行设置/偏好保持、真实桌面及正常关开均通过，见[桌面记录](architecture-e5-desktop-2026-10-20.md)。结案提交推送精确核实后进入E6a；历史准备限制保留。前批结案 `b1418dd31ab85ba554a2d895831d78453c85bb9c` 已推送，实际远程核实记录在本机 `build/architecture-e4-20261020/remote-close.json`。本轮从该干净main前像开始；E4包 `61dc981193d24b50bc84bee1c9ca1670` 的journal/EXE、冻结工具与测试实例身份已只读核实。现场没有其他发布、测试、实采或维护。

## 范围、调用方及退役

| 旧入口族 | 唯一正式位置与职责 |
| --- | --- |
| datasets/capital_actions、capital_validation、capital_archive、issue_detail | features/capital_actions 的 contract/validation/dataset/issue_contract；chain归公开契约 |
| collectors/tdx_capital_source、tdx_dividend_periods、tdx_dividend_discovery、tdx_issue_detail | source/dividend_history/dividend_discovery/issue_source；纯协议、字段、列表/分红解析各自拆出 |
| collectors/capital_lifecycle、capital_recovery、issue_prefetch、tdx_dividends、tdx_rights_issues、tdx_additional_issues | lifecycle/recovery/issue_prefetch及三独立collector |
| data/capital_actions、issue_candidates；ui/capital_actions、capital_preview、capital_words | query/issue_candidates/codec及ui/preview/words |
| contracts/adjustment；data/adjustment、adjustment_inputs；ui/adjustment、adjustment_chart | features/adjustment 的contract/query/inputs/ui/chart |

24旧文件已删除，调用方、测试patch、两显式维护入口、采集规则定位、coverage与装配映射同批迁移。没有转发模块、双注册或双写。两个bundle只提取原槽位，query不再导入采集执行器。复权沿用E4公开行情迭代器和原同连接事务；公共preparation保持原路径。

本机候选基于更早源码，未直接应用。重新从当前正式树生成64个精确目标，保存完整前像；24模块/16符号静态正文比较通过后才应用。补齐parser对纯source_protocol.result_set的显式依赖，Ruff只整理导入及删除无用导入。静态等价不充当业务运行结果。

## 请求前适用性登记

本批为组织迁移：来源参数、规范字段、金额/日期/身份、集合规则、修订、断点及恢复正文保持；不改SQL表、schema、用户设置。故新增/实质修改来源所需随机30股严格准入不因搬家自动触发。若实际审阅或回归发现业务实质变化，撤销该判断并执行额外随机30+固定反例；不能事后因来源失败豁免。

仍须取得本轮完整分红容量来源观测与正式管线证据。请求前[完整容量协议](architecture-e5-capacity-protocol-2026-10-20.md)冻结原100000来源行/1000期/128MiB/64KiB/1500ms预算；只读SQL或合成fixture不能代替。本轮工具使用PrivateStorage及共享取消/清理/恢复，保留所有旧历史并单列差异，不把准备失败改成通过。

## 当前验证（命令从项目根运行）

下列 `py` 为 `.venv/Scripts/python.exe`；每次pytest使用独立build临时目录。正式集成显式 `EMPIRE_INTEGRATION=1` 与本机13348配置路径，未输出凭据。

| 验收项 | 实际命令/证据 | 退出与结果 |
| --- | --- | --- |
| E5业务/时间语义、U开发 | `py -m pytest`：capital_lifecycle/recovery/preparation/ui、tdx_dividends/additional_issues/rights_issues/issue_details、issue_availability、adjustment/query/chart、kaipanla_public_inputs；`build/architecture-e5-20261020/domain.xml` | exit0，159 passed、2 Qt弃用警告 |
| C3/C4架构 | `py scripts/architecture_contract.py check` | exit0，386模块/1419导入、4既有债务/0新增/43退役债务 |
| C1/C2装配 | `py scripts/assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json` | exit0，精确身份/顺序通过 |
| 类型 | `py -m mypy` | exit0，8公共边界通过 |
| 容量工具安全/实际SQL | `py -m pytest tests/test_dividend_capacity.py tests/test_source_verification.py tests/test_capacity_session.py`；`build/architecture-e5-20261020/safety-sql.xml` | exit0，135 passed；真实私有库seed/正式query/跨库拒绝及清理通过 |
| 静态 | `py -m ruff check src tests scripts` | exit0 |
| R1～R4隔离 | capital_archive、issue_availability_archive、adjustment_pipeline、prefetch_pipeline；`build/architecture-e5-20261020/integration.xml` | exit0，67 passed/194.61秒；三数据集及复权独立参数/场景，当前实现 |
| C/R/U公共 | feature_bundles、assembly、architecture、UI边界、all_collector_prefetch、dataset_contributions；`build/architecture-e5-20261020/common-2.xml` | exit0，145 passed/20.49秒 |
| 新整栏目工具 | `py -m pytest tests/test_verify_capital_actions.py`；`build/architecture-e5-20261020/actions-tool.xml` | exit0，4 passed，含两个实际私有SQL/Redis管线、取消恢复与详情来源反例 |
| E5完整容量/真实来源 | 下节三条正式命令及提交JSON | exit0；容量与当前管线通过，历史完整准备限制保留 |
| T3冻结性能 | `py scripts/architecture_benchmark.py measure --test-settings <本机13348配置> --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output build/architecture-e5-20261020/performance-2.json` | exit0，原阈值18/18，incomparable为空；失败首轮另留 |
| M文档 | documentation_contract review/check、verify_documentation、verify_database_design；文档四文件回归 `build/architecture-e5-20261020/docs-2.xml` | 各exit0，230文档/1573链接/55表；41 passed/24.46秒；四页面分别记录组织迁移不影响操作的理由 |
| A4/正式发布及U1～U3 | 唯一完整发布、同包机器核验及真实窗口；见下列结案和独立桌面记录 | exit0；适用组织迁移范围已验收，来源限制保留 |

初次安全单测107 passed/1 skipped/1 failed：测试误把DeferredResponse当作UnitRead调用resolve；按正式consume契约修正测试后上述135项全部执行通过。首次两个静态CLI缺action、一次装配CLI缺baseline，各自exit2保留；补齐正式参数后通过。该早期检查点容量旧报告随路径退役失效，`verify_database_design.py`当时exit1；后由下列真实新测报告恢复，未刷新旧hash。

后续实际观察器SQL冒烟扩展首先因合成快照漏market/code、日期仍为字符串而失败，修成真实SQL行形状后通过。首次容量预检因工具误把统一状态dataset当消息dataset而exit1，在生产只读阶段拒绝、无来源请求/无私有资源；核实正式值为`dividends`后精确修正，没有放宽为多种格式。最终安全回归为 `safety-sql-4.xml`，135 passed/4.50秒。公共首轮139 passed/6 failed来自测试动态导入未迁，迁至source/issue_source后145全部通过。旧容量失效曾exit1；新实测登记后数据库设计门禁exit0，55表/49数据集/12 JSON。

### 当前完整来源和容量事实

以下均由已实现的共享PrivateStorage生命周期运行，默认use_proxy=true/proxy_fallback=true；实际direct/fallback均0。全部六项清理true，SQL/Redis残留false，未写生产业务或配置。完整SQL全表包含保留历史，源码/工具/DDL绑定和输入身份在JSON中，不修改旧报告。

| 数据集 | 实际命令（公共参数为`--test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json`） | 本轮结果 |
| --- | --- | --- |
| 分红 | `py scripts/measure_dividend_capacity.py <公共参数> --output build/architecture-e5-20261020/dividends-capacity-2.json` | exit0，5579证券/635期/58607全部来源行；池内56131条完整经5580消息归档；636代理请求，pending0 |
| 配股 | `py scripts/verify_capital_actions.py --kind rights_issues <公共参数> --output build/architecture-e5-20261020/rights-source-1.json` | exit0，1191条/766证券；1代理请求，来源→入队→正式查询集合内容一致，pending0，准备全部pass |
| 增发 | `py scripts/verify_capital_actions.py --kind additional_issues <公共参数> --output build/architecture-e5-20261020/issues-source-1.json` | exit0，6542条/3031证券；102代理请求，101必要详情请求、6415关联复用详情、52暂无详情；独立详情比较及管线一致，pending0 |

分红SQL56160条，payload总23373207字节、最大447字节；原SQLLane连续10次`list_events(code='600007', limit=51)`最大3.4475ms，原预算全部通过。完整报告见[新分红容量](architecture-e5-dividends-capacity-2026-10-20.json)，另见[配股](architecture-e5-rights-source-2026-10-20.json)、[增发](architecture-e5-issues-source-2026-10-20.json)。分红报告的代码绑定保持；其后只新增独立配股/增发验证工具及测试，未改变所绑定资本业务/测量器/SQL，不能把其较早全树摘要冒称最终全树身份。

分红29条旧键未在本轮来源出现，其中包含池外历史；正式池内审计56137条，与本轮56131条仍有差异。增发16条历史保留，1条未知历史详情仍未证实范围外；正式集合准备检查失败，暂无详情作为原来源状态保留。没有删旧历史、填补日期、伪造可用详情或冲销失败。本轮PASS仅指协议规定的容量/当前来源管线；不称历史完整、严格随机30通过或生产已采完。

T3首轮exit1：17/18，holders_browse P95 5.43936ms超过5.3032375ms，15样本中单次8.8016ms/中位3.1451ms。本批持有人查询未改；现场3秒CPU观察无遗留测试/实采，仅正常应用/代理进程。完整原工具再测exit0、18/18；工具/协议/基线/阈值保持。两轮原始报告均提交，未挑除单次样本或改阈值。迁移正文审计见[24模块/16符号](architecture-e5-equivalence-2026-10-20.json)，Ruff导入排序单列，业务运行证据如上。

## 资源交接

07时前正常Alt+F4关闭E4窗口，随后fresh枚举Empire窗口为空；未强杀进程或数据库。关闭前45任务、活动0/pending0、既有失败5。源码与安装config、插件偏好前像hash保存于 `build/architecture-e5-20261020/preflight.json`。测试13348实际UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`，原datadir、仅四系统库、无其他客户端；与生产3307不同。实例保留运行，工作结束须重新打开正式桌面。

持有人空名债券H3失败、E4严格来源失败及停复牌精确错误 `38622b7215a44fe4a5224031bdf4d963` 均保留。未清共享Redis、改用户策略或清业务数据。整个D～F任务尚未完成。


发布前检查：原48行设置payload及updated_at摘要仍为9e59d702765610a9f91bfdfcc19bcfc104590d239bd87be6dfa99a95c511c1ac，两config和原偏好均精确保留；本地前像为preflight-preserved.json及desktop-settings/preferences-before文件。13348实核UUID/datadir，仅四系统库、无其他客户会话，全局pending0、原E4包身份和冻结文件保持。首次文档测试路径拼写错误exit4/零测试，改用实际四文件后41 passed；首次文档review指出四页面正文不变，针对各页面逐项审阅并记录具体不变理由后通过，未全局豁免。

接续发布前最终复核：资源实核保存preflight-resume-resource.json，原包/私有实例/冻结输入保持、全局pending0。GitHub直连首次ls-remote失败（443连接超时），尚不能声称本轮远程已核实。最终文档复核首条命令误指不存在test_database_reference.py，exit1/零测试，随后按实际原四文件执行，未计首条通过。


## 正式发布与结案

唯一 `./verify-release.ps1` 自然exit0；release `056304060b0249828b21ac2b8fafa092` 的publication committed/passed，绑定干净实现提交 `e403faa655a4162f9a2946322a0ee25f51181ca6`。全量3770 passed、5 opt-in skipped、20 warnings/2180.82秒。24步骤、真实容量、四DPI、打包/搬移/配置及切换通过，第22步首次模板生成预期exit1，未写成0。完整源输入 `bcfc1b2ce7842101d52de53ebfbe9b4717648b8d48fe06a3b47932ae6473c227`，EXE `6b9ceff7ba1f78dc3fdc6925c023335047c38bb26253e85017bdcb03931b6881`，树 `a506088bb3e4df4a6efb7322cfeeefa9aeca12d135905c2f8c28307dfb14a27d`。

[发布审计](architecture-e5-release-evidence-audit-2026-10-20.json)实际重核1556输入/54输出及原JUnit；5跳过均为显式state-unit维护演练，本批未修改该路径，不计通过。该审计先于结案文档，不宣称完整输入仍与结案文档相同。

07:57～08:26真实可见窗口逐项验证四页/详情/帮助、滚轮、草稿保留和撤销、UI独立启停、collector单停时实际命令拒绝、依赖保护及928×892窄窗；随后正常关开。[同包报告](architecture-e5-post-release-2026-10-20.json)和[设置审计](architecture-e5-settings-restored-2026-10-20.json)证明两config、原偏好及全部48设置payload/updated_at保持；C:/Windows下正式EXE真实连接通过，三资本正式查询与复权查询正常。最终窗口6819044工作台可见，活动0/pending0/既有失败5。全部适用U项与实际动作限制见[独立桌面记录](architecture-e5-desktop-2026-10-20.md)，不由离屏或静态等价替代。

E5验收矩阵：C1/C2身份顺序与C3/C4单一路径由上列装配/架构及迁移审计覆盖；R1～R4由67隔离及159领域专项、135安全与145公共回归覆盖；E5来源/容量按三原始报告范围判断，严格随机30不自动适用，历史完整准备仍失败；T3首轮失败保留、最终18项通过；M由最后review/check及四文档回归覆盖；A1～A3实现未改，沿既有保护证据，A4由本轮完整发布/实际桌面覆盖；D1～D3诊断实现未改，不另造故障环境。H3严格来源与E4失败仍独立保留。

最终结案文档review/check、verify_documentation及verify_database_design均exit0；231文档/1583链接/55表。原四文档回归实际exit0、35 passed/27.20秒，原JUnit `build/architecture-e5-20261020/docs-close.xml`，未新增实现测试或重打包。

08:20资源核实：自有13348实际UUID a3e8a5eb-cb64-11f1-8ddf-380525361d4e、原datadir、仅四系统库/无其他客户端；全部来源私有资源已清，无测试/实采/发布并行。实例运行供后批；生产3307、Redis及未解决错误未动。E6a～F未实施，最终优化尚未完成。纯结案文档不重新打包、不改变EXE身份；本批提交及远程精确结果在实际push后核验。
