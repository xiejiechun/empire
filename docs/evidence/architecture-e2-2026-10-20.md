# E2 指数、行业与指数行情实施记录（已验收）

状态：E2全部适用出口已验收，结案文档待提交推送。实现提交 `ccc04f399fcaa5d8815da6a1e1b17df72a541620`；唯一正式发布 `2fa960ba05f047fdbbbc6ca214b0000c` committed/passed，门禁exit0、3679 passed/5显式opt-in skipped/20 warnings。配置、异cwd真实连接、正式查询和同包可见桌面、U1/U2、正常关开均完成，详见[真实桌面记录](architecture-e2-desktop-2026-10-20.md)与[同包机器报告](architecture-e2-post-release-2026-10-20.json)。前批E1结案4b30fcc已推送核实；本批推送核实后第一项为E3，E3～F仍未实施。

## 输入与范围

开工工作区干净；本轮已有改动全部为E2实施，保留原字节前像于本地 `build/architecture-e2-20261020/preimage/`。本地preflight核实E1发布 `7ad607fa635c4f36b662b324dc501e52`、自有13348实际server_uuid与3307不同、仅四系统库、共享pending=0、原config/偏好及冻结文件SHA不变。恢复时仍为main/4b30fcc、正式桌面仍运行E1；没有将E2源码当作已安装包。

三业务的contract/source/collector/dataset/query/UI共19模块迁入 `features/indices`、`features/industries`、`features/index_prices`；旧模块删除、调用方/测试patch/规则/coverage/装配归属同步。`index_code`移至公共security，`digest`移至指数公开contract，HTML Node/Document/one移至sources/ths_catalog_html。bundle保留原插件、任务、数据集、schema、页面及槽位。不改DDL、持久化键或用户策略，不增加转发、双登记、双写或启动迁移。

原同名旧实采与容量脚本不满足安全执行条件。本轮已改接共享私有生命周期与CapacitySession，补齐真实server_uuid、UUID资源归属、逐连接检查、失败/取消/清理和最终报告保护，经安全反例后执行下列新测。目录与指数行情均非股票采集粒度，30股票门槛不适用，不能宣称满足随机30股；替代证据为完整目录/成员与有限固定指数年度链路集合及内容核对。固定行情反例 `399317/2014-12-05` 负成交额保留，不能填零或移除。

## 适用验收与已执行命令

| 验收 | 状态/证据 | 限制与剩余工作 |
| --- | --- | --- |
| C1/C2 装配身份与顺序 | 最终assembly-final.json exit0，精确身份、语义、映射与完整顺序保持 | 不只比较数量 |
| C3/C4 依赖与旧入口 | architecture-final.json exit0，342模块/1336导入/46既有债务/0新增/1退役；mypy7严格文件exit0；19旧模块引用0及定义等价 | 既有债务不冒称全部消除 |
| E2/R1/R2 领域语义 | 定向pytest首轮118 passed/3 failed（动态旧行业import），修复调用方后domain-final.xml：121 passed，exit0，1.87秒 | 不替代隔离归档、实际来源及正式查询 |
| R3/R4 恢复/共享路径 | 67项隔离、147安全、408公共/装配/UI回归均exit0，JUnit见本地integration/safety-final/public-final.xml | 完整发布仍须全量门禁 |
| H3/来源适用范围 | 非股票粒度，30股票不适用 | 安全工具、完整目录/成员及固定五指数136年正式E2E已通过，见下文；严格持有人来源失败保持 |
| 容量 | 四份真实新测exit0，六张设计卡同步，见下文 | 其余13份绑定保持；行业legacy_baseline，分红完整容量待办保持 |
| T3 | [本轮报告](architecture-performance-e2-2026-10-20-1.json)，18/18通过、无不可比项、清理成功 | 原冻结协议/工具/基线/阈值保持；非网站吞吐或可见桌面 |
| M/文档 | 最终语义review/check/verify及35项文档回归exit0 | 三包README、业务/程序内说明和覆盖关联已同步，逐功能具体不变理由保持 |
| U1～U3 | 已验收；[桌面操作](architecture-e2-desktop-2026-10-20.md)、[机器核验](architecture-e2-post-release-2026-10-20.json)，CLI exit0 | 单停页面/采集器及依赖保护、草稿撤销/滚轮、选择/滚动、窄窗口、原配置偏好、真实连接与查询、正常关开完成；设置全表前像限制如实保留 |

已实际运行：`ruff check src scripts tests --fix` exit0；`python -m mypy` exit0；`python -m pytest tests/test_ths_indices.py tests/test_ths_industries.py tests/test_ths_index_prices.py tests/test_industry_ui.py tests/test_index_price_ui.py tests/test_all_collector_prefetch.py --basetemp build/pytest-e2-domain-final --junitxml build/architecture-e2-20261020/domain-final.xml -q` exit0。完整日志在本地build，必要脱敏事实随结案提交。

## 资源与恢复（以下保留开发时序检查点）

恢复新增事实：67项隔离集成exit0（212.93秒，integration.xml），147项工具安全反例exit0（3.08秒，safety-final.xml），19模块/5符号定义AST等价及旧文件退役检查exit0（equivalence.json）。静态等价不替代真实链路。恢复preflight-resumed.json核实实际实例、原配置偏好和冻结文件保持。正式E1窗口已Alt+F4正常退出，fresh枚举无Empire；关闭前工作台活动2/pending0/失败5，显示停复牌603517的2026-10-19与2026-10-20来源内容冲突。关闭后共享pending1，保留原消息和未解决错误，不能手工清队。E3再按实际错误ID调查，本轮私有队列与生产队列分别验收。

安全容量入口已接共享CapacitySession，保留100×1000成员/1000×100日、20次查询与全部原阈值，保存原始samples并校验完整业务集合；未执行测量。共享helper新增subject使持有人与THS资本原报告绑定失效，必须追加两份真实重测，不能只改hash。来源入口已复用共享私有生命周期，非股票范围明确拒绝混入股票抽样声明；147安全回归不等于实采。当前verify_indices.py使用私有13348、严格代理执行两类完整目录，输出catalogues-source-1.json；运行中不修改源输入，不提前写通过。

目录实际完成：`python scripts/verify_indices.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --kinds indices industries --proxy-only --output build/architecture-e2-20261020/catalogues-source-1.json` exit0。run `d6d955dda42549abb10cec94f45291b4`，输入 `369636112c6c21e27aae87a0158b941f94830e4b50ae3a9259164c0fed504068`。指数571项/99516成员、572来源单元及572正式入队单元、代理572；行业90项/5575成员、91来源单元及1整份正式入队单元、代理91。均公开目录/成员查询全量键与内容相同、私有pending0、无直连/回退；36项来源明确暂无成员按原语义保留，不推断真实零成员。两个业务和整轮pipeline/strict_proxy实际通过，sample_30_applicable=false/sample_30_met=false；所有关闭、SQL/Redis、锁及连接清理成功，无剩余私有资源，原配置/输入最终复核保持。此结果不证明历史调样或30股票准入。随后执行verify_index_prices.py固定五指数全部可得年度，仍在运行，不能提前通过。

行情实际完成：`python scripts/verify_index_prices.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --proxy-only --output build/architecture-e2-20261020/index-prices-source-1.json` exit0。run `58116690415e47d5922dcedc9903f007`、相同source摘要。先在新私有库走完整真实指数目录链路，再验证399411（18年4319日）、1A0001（37年8744日）、399001（36年8699日）、1B0300（22年5290日）、399317（23年5269日），合计136年度32321日。141个行情来源单元/141个正式入队单元，146次行情代理请求，无直连/回退。SQL年度集合、内容、头证明与每年度公开列表/图表全部一致；audit complete=true/problems=[]，pending0，所有私有资源清理及源/配置最终核验通过。固定399317/2014-12-05负成交额仍为负且正式查询volume_amount_valid=false；准备结果记录1条量额异常，不影响既有收盘收益用途，不允许依赖量额策略使用该日。没有把年度完整改成全字段适用或30股通过。

正式来源机器证据：[目录链路](architecture-e2-catalogues-source-2026-10-20-1.json)、[行情链路](architecture-e2-index-prices-source-2026-10-20-1.json)。成功正文只用于本轮内存比较，不提交响应全集；ownership秘密只留本地build。

## 实际容量新测

扫描全部17份active measured报告，仅四份绑定失效（本地capacity-impact-before.json），其余13份保持原报告；行业仍为明确legacy_baseline，不冒称新容量已完成。实际新测全部exit0，实际MySQL8.4.9/13348/上述UUID/flush=2/sync_binlog=1/log_bin=0，原始计时、条件、集合/修订、DDL/源码绑定和独立清理记录保留。四报告都在清理完成且输入最终核验后才passed；六张受影响设计卡指向实际新报告，verify_database_design.py exit0（55表/49数据集/12JSON）。未改历史报告hash或原阈值。

| 实际命令（均使用上述--test-settings） | 新证据 | 主要结果与适用范围 |
| --- | --- | --- |
| measure_indices.py --output docs/evidence/architecture-e2-indices-capacity-2026-10-20-1.json | [目录容量](architecture-e2-indices-capacity-2026-10-20-1.json) | 原100指数/100000成员；导入1.846s；四项P95 1.158/1.800/4.403/8.461ms；audit0.535s；分配15269888B；全键/内容核验、重复0DML/修订2写 |
| measure_index_prices.py --output docs/evidence/architecture-e2-index-prices-capacity-2026-10-20-1.json | [行情容量](architecture-e2-index-prices-capacity-2026-10-20-1.json) | 原1000指数/100000日行；导入4.093s；P95 2.367/6.441ms；分配12763136B；1000完整年度键/内容核验、重复0DML/修订2写 |
| measure_holders.py --report docs/evidence/architecture-e2-holders-capacity-2026-10-20-1.json | [持有人补测](architecture-e2-holders-capacity-2026-10-20-1.json) | 原2500主体×4期；导入53.745s；正式独立audit最大11.932s、三项合计23.763s；分配208175104B；保留所有原样本/上限 |
| measure_ths_capital.py --report docs/evidence/architecture-e2-capital-capacity-2026-10-20-1.json | [THS资本补测](architecture-e2-capital-capacity-2026-10-20-1.json) | 原700证券10500事实；导入18.462s；三项P95 2.765/1.110/3.535ms；audit1.891s；分配19021824B；重复0业务DML |

以上为私有放大样本容量，不代表生产覆盖、网站吞吐或断电耐久性。分红完整容量待办与严格持有人H3失败保持。

自有13348前置UUID为 `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`，datadir `build/architecture-evolution-20261019/mysql-data`，秘密配置只在本地build、不提交。恢复会话仍须现场核实。正式E1窗口16058676在隔离实采/T3前已正常关闭，fresh枚举无Empire，发布验收结束须重开。未操作生产业务数据、共享Redis服务或RouterProxy目录。当前没有本轮来源/容量私有业务资源。

## 发布前最终审阅与恢复检查点（历史）

本地最终定向命令：`python -m pytest`运行public-final.xml对应业务/装配/UI/共享用例，408 passed/exit0（26.65秒）；ruff exit0，mypy exit0（7严格文件），装配/架构最终检查均exit0。冻结T3按acceptance第9节原命令、原协议/基线运行一次，18/18通过，原始样本、环境与清理见正式报告；没有改工具或阈值。

文档已修改三包README、三篇来源说明、架构/规则/覆盖及程序内技术主题；首次review拒绝129项可达来源变化，逐项核对后通过正式CLI记录具体不变理由，未放宽门禁。本地documentation-unchanged-review.json保留逐功能依据；账本更新后已再次review/check/verify，均exit0（215篇/1505链接/55表）；35项文档回归exit0（28.64秒，docs-final.xml）。当前未称发布或已验收。

最后生产只读命令`python -m empire doctor --project tdx-suspensions`实际exit2，status=partial；错误/队列已读取，隔离内存快照不可知，不冒称完整通过。精确未解决错误ID `38622b7215a44fe4a5224031bdf4d963`：603517、2026-10-19与2026-10-20来源内容冲突；保留该错误及生产pending1，E3调查。未清理旧或并发新增错误。此生产遗留不属于E2私有pending0证据。

发布前独立一轮只读证据审核exit0：[机器审阅](architecture-e2-pre-release-audit-2026-10-20.json)。从JUnit重算778项全部通过/0跳过，复算T3全部统计及18项阈值，并核实来源/容量/等价证据与当前源输入；17份active报告绑定全部有效，未写已发布或桌面通过。原配置/偏好和冻结文件保持；test仅四系统库、无其他客户连接；生产pending1仍保留。远程有界直连ls-remote已恢复exit0，main为4b30fcc，与当前前批HEAD一致。接下来形成实现提交后冻结输入运行唯一完整门禁。


## 正式发布与同包核验检查点

完整发布约01:17～01:58完成，24步骤全部exit0；1443输入及54份retained输出经独立审阅保持，JUnit重算3679通过、5显式opt-in跳过、0失败，耗时2258.97秒。跳过不计通过，本批未修改state-unit语义。容量quick、四档DPI、打包、中文空格搬移/配置smoke与正式切换通过。完整输入 `c3f1a25884bbab7a61fb9fbbbdaafac9ff1205d170dce55eb6afbfc037cc6a32`，冻结干净提交ccc04f3。

本地audit_release.py及check_published_runtime.py均exit0，分别保留release-evidence-audit.json及post-release-read-only.json；安装manifest/EXE/tree与journal一致，两config及原偏好字节保持，正式EXE从C:/Windows运行doctor的Redis/MySQL连接通过。正式源码API读取指数/行业目录、成员、分页及399317列表/图表和负成交额质量标记通过，明确不代替EXE页面。该只读报告actual_desktop=pending保留，真实桌面另记。

可见正式窗口658542已观察ccc04f399fca干净版本、本地连接；指数上证1A0001目录及成员第一页、第二页200条实际呈现。归档页面观察pending0，由正式流程处理原pending1，未手工清队。U1/U2、行业与行情、偏好恢复及正常关开仍待继续。

## E2最终结案

上列“未执行/仍在运行/未称发布/待桌面”均为对应时间的历史检查点，当前结论以本节及开头矩阵为准。正式发布、1443输入/54输出/24步骤退出码及JUnit重算详见[发布机器审阅](architecture-e2-release-audit-2026-10-20.json)。最终EXE `18f05709ca2c7855f6395c1c8c2c09f6eb58c176c699b00da38a460070a24652`，树 `b1eff9327f678d57a57d88c5eb322f82a23e4da69a7e370be3502329d3eff005`，与committed journal及02:33同包复核一致。

适用ID：C1/C2身份及顺序、C3/C4依赖及旧入口、R1～R4业务/集合/恢复/唯一归档、E2目录及行情/容量、T3、文档审阅与U1～U3均已有实际命令、exit0及引用证据。A1～A3和诊断D1～D3本批无行为修改，完整门禁覆盖原专项；现场doctor partial与未解决错误如实保留，不称D1现场全通过。M1/M2/M3与其余F收束仍待F执行，不将本批文档同步计作F完成。H1/H2仅因容量helper绑定追加持有人/资本实际容量；H3严格来源失败保持，本批目录/行情非股票粒度不声称30股通过。19旧模块、5符号的迁移及调用方退役清单见equivalence与assembly证据。

结案仅新增事实文档及机器报告，不改源码、测试、SQL、配置或已发布EXE，不需要再打包。最终文档review/check/verify及35项相关回归后形成结案提交，实际推送main并核远程，再开始E3。限制：行业legacy_baseline、D固定空名债券严格H3失败、分红完整容量待办、停复牌错误38622b7215a44fe4a5224031bdf4d963均保留，不影响本批已证明的组织迁移范围，也不代表整个项目已完成。

结案文档实际验证：`documentation_contract.py review --note <E2同包桌面与设置限制具体审阅>`、`documentation_contract.py check`、`verify_documentation.py`、`verify_database_design.py`均exit0，216篇/1515链接/55表/49数据集。验收10.1四个指定文档测试文件35 passed，exit0、29.42秒，JUnit本地`build/architecture-e2-20261020/docs-close.xml`。`git diff --check`通过；相对ccc04f3的src/scripts/tests/sql无差异。结案远程首次有界直连核实退出1（GitHub443连接超时），保留失败，推送前使用现有网络配置重试，不修改用户保存配置。
