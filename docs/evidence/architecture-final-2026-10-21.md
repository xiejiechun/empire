# 模块化优化 A～F 最终逐项交付报告

2026-10-21：A～F代码组织、公共边界及维护工具的适用实施、开发验证、逐批正式发布和同包真实桌面均已验收。F最后发布为干净`280a7da912a06cd522f2ea407eee4a816bad4703`、release `4f8f55d07a274ad4adfe78a34f815076`。本结论限已登记的组织迁移和修复范围；**H3严格来源完整性、E4严格来源完整性及资本历史准备仍有失败，不能宣称所有业务来源已全部验收或全市场已采完。**

本报告汇总既有真实证据，不重新运行来源或发布、不改写历史失败。各阶段原文中“下一批未开始”保留当时时态；当前顺序和结果以本报告及[状态账本](../architecture-evolution/status.md)为准。

## 实际修改与退役路径

业务进入`features/`：news、holders、financial_statements、indices、industries、index_prices、stocks、calendar、suspensions、preparation、kaipanla、capital_actions、adjustment、ths_capital、listings、listing_status、security_aliases、name_changes、st_events、unlocks、unlock_industries、performance、repurchases、trading_rules。各包README提供定位及本地帮助权威；SQL归属资源接入唯一登记。E6g退役最后的`features/remaining.py`及相关旧入口。

逐批迁移了调用方、静态字符串、测试patch目标、文档、资源与构建声明；无转发兼容层、双注册、双写或启动自动迁移。具体旧→新清单在下表各批记录和`docs/assembly-migrations.json`，不由文件数量推定等价。稳定插件/任务/数据集/schema/job/namespace/page及六类顺序由精确契约核对，保存设置由同包快照核验。

共享下载、代理、限流、预取、入队、统一归档、摘要、调度、SQL执行和公共UI继续各一条正式路径；公共preparation路径保持。F以唯一`shared_to_business`规则替换剩余窄分支、校准三项元数据，严格mypy从原8公共文件扩至13；143主题改为单源权威片段+确定性聚合，发布只读check及包字节校验。影响报告只建议测试，完整发布仍全量。首包真实帮助折叠卡死通过公共标准无障碍模型重置通知修复，真实Qt接口反例和新包实际交互均验证。

## 批次与输入身份

每行记录包含该批命令、退出码、输入/样本身份、旧入口、容量、T3、发布、桌面及限制；后续纯证据提交与已发布实现提交区分。各批唯一正式入口均为`./verify-release.ps1`，下表最终发布均exit0，原失败另保留。

| 批次 | 已发布实现 / release | 正式实施与最终证据 |
| --- | --- | --- |
| A/B | e4dafe72b676 / 7feb3f35333d4404aae8684dd2f6ddf6 | [发布保护、诊断、真实桌面](architecture-ab-2026-10-19.md)，3403 passed；前两轮问题保留 |
| C | 81e147f / 8fbd5bd7a9cf460a9b82022b7e643f1d | [新闻样板](architecture-c-2026-10-19.md)，3494 passed、有限代理新闻50条 |
| D | b7f452a / de8532b2a7f146d184964805b5694b66 | [股东复杂样板](architecture-d-2026-10-19.md)，组织迁移已验收，严格H3失败单列 |
| E0 | 99e69db / 8ba4515618874a4dae5fbdaba42d04d7 | [SQL归属](architecture-e0-2026-10-19.md)，3660 passed |
| E1 | a228421 / 7ad607fa635c4f36b662b324dc501e52 | [财报三表](architecture-e1-2026-10-19.md)，3669 passed |
| E2 | ccc04f3 / 2fa960ba05f047fdbbbc6ca214b0000c | [指数/行业/指数行情](architecture-e2-2026-10-20.md)，3679 passed |
| E3 | d062234 / 08dd70b018394bc2bdf673bc3d8b7b99 | [基础/准备/目录](architecture-e3-2026-10-20.md)，3733 passed；注入行为实际验证 |
| E4 | acb466a / 61dc981193d24b50bc84bee1c9ca1670 | [开盘啦七项](architecture-e4-2026-10-20.md)，3755 passed；严格来源失败单列 |
| E5 | e403faa / 056304060b0249828b21ac2b8fafa092 | [资本事件/复权](architecture-e5-2026-10-20.md)，3770 passed；完整分红容量通过、历史准备差异保留 |
| E6a | 4550a9e / 7d92659ce1604c3a918e4317f4f7caa6 | [同花顺资本](architecture-e6a-2026-10-20.md)，3773 passed |
| E6b-listings | fec74bc / a2382f717972436d83956faefdfebda6 | [上市发行](architecture-e6b-listings-2026-10-20.md)，3780 passed |
| E6b-status | 230c5d2 / dad5a84751e44fe1a6f35ef4e577c7b0 | [上市状态](architecture-e6b-status-2026-10-20.md)，3786 passed |
| E6b-aliases | b96abe2 / e50fe39d6083405ab7abaf86d90a2561 | [代码映射](architecture-e6b-aliases-2026-10-20.md)，3793 passed |
| E6c | 0e59ccc / 689a04ad03ee4cdba386f39438e704f3 | [更名/ST](architecture-e6c-2026-10-20.md)，3802 passed |
| E6d | 7b1fb83 / 0cc06d1a846f42e78088bfad72ccfcd4 | [解禁](architecture-e6d-2026-10-20.md)，3823 passed；两轮门禁失败保留 |
| E6e | 5bcffb7 / 455c9c6d（全ID见记录） | [业绩/股东变动](architecture-e6e-2026-10-20.md)，3835 passed |
| E6f | 0c2ab3c / 7f5acbb5（全ID见记录） | [回购](architecture-e6f-2026-10-21.md)，3840 passed |
| E6g | 7373f38 / 7e85c4e4db9f47bdbd5a137e731c7041 | [交易规则](architecture-e6g-2026-10-21.md)，3844 passed；结案5802df6已推送精确核实 |
| F | 280a7da / 4f8f55d07a274ad4adfe78a34f815076 | [实现](architecture-f-2026-10-21.md)、[修复](architecture-f-desktop-repair-2026-10-21.md)、[同包真实桌面](architecture-f-desktop-2026-10-21.md)，3972 passed |

所有最终全量发布均有5个原state-unit显式opt-in skips，均不计通过。不是以累计测试总数或相同行数宣布迁移完成。

## acceptance.md逐编号结论

下列命令中Python为`.venv/Scripts/python.exe`。完整运行参数、独占basetemp/JUnit、输入hash、随机种子、时间、原始报告与清理见所引阶段证据；本表不将同名旧脚本或旧输入视为当前证明。

| 编号 | 适用范围 / 输入与实际命令 | 退出码、结果、证据与限制 |
| --- | --- | --- |
| A1 | 正式发布全过程互斥；release pipeline/entrypoints/steps/output专项及每批正式门禁 | 0，通过；[A/B](architecture-ab-2026-10-19.md)含第二发布拒绝、子进程所有权和失败回收；F[25步审计](architecture-f-release-audit-2026-10-21.json)续验，未删除锁 |
| A2 | 最终提交/内容/stat/证据身份；`tests/test_release_pipeline.py`、gate及E6d反例 | 0，通过；[E6d](architecture-e6d-2026-10-20.md)保留原失败及修复反例，F1978输入无失配；未改冻结release_lock |
| A3 | 失败、中断、占用、配置与journal恢复；发布专项+唯一门禁 | 0，通过；[A/B](architecture-ab-2026-10-19.md)及F原始步骤；首包GUI失败单独记录，不能将发布成功代替桌面 |
| A4 | writer→reader、真实声明、包smoke及安装身份；`verify-release.ps1`和`audit_repair_release.py <run> <head>` | 0，通过；F3972 passed/5原skip，EXE/tree/source精确身份见[桌面结案](architecture-f-desktop-2026-10-21.md)；当前包仍280a7da |
| D1 | B项目诊断；`python -m empire doctor --project <ID>`，真实新闻/财报/股东/KPL | 0/partial按各项原状态保留，能力通过；[A/B](architecture-ab-2026-10-19.md)列时间、确切错误ID、队列/范围/未知，不声称进程内隔离可见 |
| D2 | 预算、限额、一侧故障仍返回；project diagnostics及真实MySQL隔离集成 | 0，通过；[A/B](architecture-ab-2026-10-19.md)3真实SQL集成，SQL≤10/Redis≤20/时间正文上限；真实连接初始化计入预算 |
| D3 | 只读诊断前后状态、线程回收；诊断专项/真实报告 | 0，通过；[A/B](architecture-ab-2026-10-19.md)，不启动collector/archive、不清错误、不刷新摘要；不是生产全历史审计 |
| C1 | 业务贡献精确身份与归属；assembly/feature_bundles/dataset/manager专项 | 0，通过；逐批迁移证据+F138架构装配回归；不是只比较总数 |
| C2 | 六类顺序、纯声明无副作用、重复/环/缺依赖拒绝 | 0，通过；`assembly_contract.py check`及order专项，各批精确快照；[F开发审计](architecture-f-development-audit-2026-10-21.json) |
| C3 | 跨业务私有依赖、query/UI/dataset到执行器、共享到业务依赖 | 0，通过；F architecture check为409模块/1463导入、existing/new debt均0；统一shared_to_business反例完整，静态图不宣称任意反射沙箱 |
| C4 | 旧入口/调用方/配置/测试/说明退役 | 0，通过；逐批清单和`assembly-migrations.json`；E6g remaining退役，F无转发和双分支 |
| R1 | 重复免DML、有效修订、迟到旧版、冷热摘要、提交后重放 | 0，通过；各批领域和UUID隔离集成；F明确13348运行calendar/stock/THSstock/news四文件40 passed/102.13秒，最终全量再验 |
| R2 | 集合、同数异集、缺页/关联、边界、来源质量 | 程序反例0，通过；D48证券/E4七kind实际管线与缺口分开；严格来源仍失败，不能把专项通过扩展为来源全部可用 |
| R3 | 单任务非重叠、结束后间隔、暂停恢复、取消预取和额度 | 0，通过；每批公共生命周期、unit_prefetch/prefetch_budget/manager及私有取消清理反例；原周期/策略身份不变 |
| R4 | 入队后继续下载、统一独立归档、即刻唤醒/60秒扫描、成功清队 | 0，通过；archive_fairness/live/prefetch及各领域隔离集成；无逐批串行等待或第二队列，真实范围pending0见各来源报告 |
| U1 | 同包UI/collector独立启停、共享依赖保护 | 已验收；各批真实桌面；F实际停股东UI/collector、发命令被拒绝、HTTP直接停用拒绝并恢复，未执行被停任务来源请求 |
| U2 | 按需页面、草稿/滚轮/刷新/选择滚动、只读取消/写保留 | 已验收；专项0及各批桌面；F30→29未保存跨刷新/重建保持再撤销30，股票身份/滚动保持，974px实际窄窗及帮助历史重建；竞态不冒充全部人工复现 |
| U3 | 原设置/稳定身份、异cwd真实连接查询、可见包身份与正常关开 | 已验收；F三轮只读均0，原两config/偏好字节及48设置不变，最终工作台可见；动态45任务/活动0/失败3/pending0不是永久状态 |
| H1 | 一个持有人任务、一次必要HTML三栏、response_group和公共HTML | 0，通过；[D](architecture-d-2026-10-19.md)身份、资本消费者及48证券管线；F不另增路径 |
| H2 | 并列排名、缺口/空栏、首缺口恢复、同数异集、补齐/重放 | 0，通过；D116项私有集成、领域反例及最终全量；来源缺值不造名 |
| H3 | D严格来源完整性：冻结30随机+18固定，48全代理、实际链路 | **exit1，失败**；pipeline一致、pending0/清理成功但固定300398.SZ/2023-12-31、601515.SH/2024-06-30空名债券使acceptance_complete=false；不换样、不豁免。组织迁移适用范围按请求前D-07/6.1独立接受 |
| M1 | F三类私有副本定位/修改演练；`locality_drills.py --execute`最终run75293 | 0，通过；[原报告](architecture-f-locality-2026-10-21.json)，页面/来源局部、新业务最多一中央白名单；首remove-only的ValueError失败保留，实际分段feed注入才触发原断言；不是桌面或新来源验收 |
| M2 | 143完整主题单源、重复生成稳定、异常主题/链接/覆盖反例 | 0，通过；[F](architecture-f-2026-10-21.md)最终182帮助专项及[修复](architecture-f-desktop-repair-2026-10-21.md)217回归；唯一权威片段、聚合跟踪但不手写，包内字节另核 |
| M3 | 最后语义review/schema3、coverage、只读发布check、真实阅读导航 | 0，通过；F发布门禁和143包内核对，实际搜索/章节/help链接/历史/空态通过；结案文档另执行最终审阅及相关回归，不重打包 |
| T1 | 保守影响报告；`pytest tests/test_change_impact.py`及三类实际CLI | 0，通过45项；[F](architecture-f-2026-10-21.md)新闻134/股东131文件、公共234全量；首误判失败保留。选中不代表已运行，正式门禁始终全量 |
| T2 | 真正公共类型；`python -m mypy`、Ruff及领域专项 | 0，通过；原strict8保持+5=13，三项外部载荷Any及D RawReport/RawGap边界有解释；未放宽ignore或以cast隐藏错误，不称全项目严格类型 |
| T3 | 最终修复源db18e010；原冻结architecture_benchmark measure完整命令 | 0，通过18/18、incomparable空、cleanup=true；[真实报告](architecture-f-tree-t3-2026-10-21.json)，cold median1192.947/p951243.88254ms；全部早期失败保留，原阈值/协议/基线不改，未测网站吞吐 |

## 容量、来源失败及不适用项

路径/绑定变化均生成新的真实容量报告。F预览七kind+100000同秒点、原30次/预算与六清理通过，更新七设计卡；[17份当前绑定审计](architecture-f-capacity-bindings-2026-10-21.json)有效，未刷新旧报告hash代替测量。E5完整分红容量已完成5579证券、635期、58607来源行/636代理请求，池内56131条经5580消息归档，原预算通过，不能再写成只读诊断或待办。

以下仍为失败或范围限制，构成后续业务质量工作，不算本轮组织迁移的通过项：

- H3上述两个固定空名债券；原实采严格FAIL，不填补名称。
- E4严格实采exit1、269有效/46缺口、519代理/直连0/回退0，sample_30_met=false、acceptance_complete=false；私有pending0/清理不抹去来源缺口。组织范围按请求前登记接受。
- E5分红29条旧键未在当前来源出现、池内历史集合仍有差异；增发16条历史保留及1条未知详情，完整历史准备仍失败。生产旧记录未删除。
- 上市状态生产历史freshness、各来源公布/可用日期等限制见对应证据，当前来源管线通过不自动代表历史用途全部满足。
- 停复牌未解决错误`38622b7215a44fe4a5224031bdf4d963`未修未清；未因一次成功清空任何项目错误。

F没有实质改采集或解析，本批随机30股实采不适用，不称本轮新30股通过。各E批不按股票/固定完整响应的适用边界和样本证据见各批记录，未剔除失败样本。F可选最小schema成本优化未采用，未做配对收益实验、不称提速；完整UUID库/namespace、完整schema和全Engine守卫保持。

## 资源、发布与Git交付

同包真实桌面、配置hash、48设置hash、正式查询范围、正常退出/重开及原观察时间见[F桌面结案](architecture-f-desktop-2026-10-21.md)。最终窗口4197432保持可见。自有13348在UTC07:41:34正常SQL SHUTDOWN，实核UUID/datadir/四系统库/无其他客户端，目录保留；[原报告](architecture-f-private-mysql-close-2026-10-21.json)。生产3307和共享Redis未关闭未清理，没有遗留本轮私有库/namespace或维护任务。

结案仅更新证据与指南，不修改产品源码/包内资源，不再运行已成功的正式发布。发布审计和三轮只读报告的原`actual_desktop`待分离观察字段保持，桌面结论来自实际操作记录。最终文档检查与结案远程精确结果在实际执行后附录；在其确认前不声称已推送。


最终结案文档检查已执行：显式`documentation_contract.py review --note <本轮具体审阅>`（保留逐消费者具体不变理由）、`check`、`verify_documentation.py`和`verify_database_design.py`均exit0；408文档/2392链接/55表、49数据集/12JSON字段。原四文件文档与帮助回归使用`--basetemp build/pytest-f-closure-docs --junitxml build/architecture-f-20261021/closure-docs.xml`，exit0、40 passed/59.82秒，无skip。实际参数、日志及JUnit摘要见[结案检查](architecture-f-closure-checks-2026-10-21.json)。该报告由实际子进程退出码和原JUnit产生，未手写通过标志。源码及包内资源无本轮结案差异。
