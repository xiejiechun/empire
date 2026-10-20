# E6f 回购模块迁移实施记录

状态：开发验证通过，待唯一正式发布与同包桌面验收。整个优化尚未完成，不进入E6g/F。

## 前像和范围

main/b46326ca4e362d5002354793e94b7eeb39610576，开工工作区干净；前批E6e发布455c9c6d及同包桌面已完成，推送ls-remote精确匹配。当前目录为build/architecture-e6f-20261021（下称out）。out/preflight-resource.json实际核实旧安装EXE、config/偏好摘要、独立13348真实UUID/datadir/仅系统库与无其他客户端；生产实例UUID不同，全局pending0，冻结文件原字节保持。未修改共享服务。

五旧路径→新路径、逐字节前像、所有改动调用方见out/preimage.json；contracts/repurchases、plugins/collectors/eastmoney_repurchase、plugins/datasets/repurchases、plugins/data/repurchases和plugins/ui/repurchases已退役。目标features/repurchases内contract/collector/dataset/query/ui/bundle/README；remaining仅移本批声明，保留交易规则。原plugin3500/3600/3700、task1100、dataset1100和schema/job/page身份保持，无兼容层、双写、DDL或启动迁移。

纯组织迁移五模块去导入AST逐项相同，函数/字段/异常/请求/断点与恢复保持；原贡献语义和六类顺序由正式assembly check核对。所有生产导入、测试patch、coverage、ownership、规则source_file同步。公开preparation路径未动。

## 验收矩阵与执行

| ID | 适用范围和当前结果 | 命令/证据 |
| --- | --- | --- |
| C1/C2 | 精确身份/语义/顺序与单一贡献所有权，当前通过 | architecture_contract.py check --output out/architecture-1.json，assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json均exit0；snapshot out/assembly.json |
| C3/C4 | 五旧实现及引用退役，无新增债务，当前通过 | architecture408模块/1463导入/0债务/45退役；out/organization-equivalence.json；历史证据及计划迁移清单保持 |
| R1/R2/R3/R4与U开发 | 回购来源、字段NULL/十进制、分页/总数/失败不推进、冷热摘要、修订/旧响应/提交后重放及清队、页面等领域隔离验证通过 | 显式EMPIRE_INTEGRATION=1、独立13348；pytest tests/test_repurchases.py tests/test_repurchase_ui.py tests/integration/test_repurchase_archive.py tests/test_repurchase_verification_tools.py --basetemp build/pytest-e6f-domain --junitxml out/domain.xml -q，exit0，15 passed/37.16秒 |
| R2工具安全 | 原生产写入旧实采入口已替换；实际私有schema初始化/全链路SQL正例、错实例/跨库/同数异内容/取消、共享cleanup和恢复反例通过 | pytest tests/test_source_verification.py tests/test_repurchase_verification_tools.py tests/test_capacity_session.py --basetemp build/pytest-e6f-safety --junitxml out/safety.xml -q，exit0，129 passed/6.41秒 |
| R公共与U架构 | 318项通过/148.12秒 | 既定C/R公共及UI架构、调度/预取/资源/隔离归档公平测试；out/public2.xml，exit0 |
| E6f真实来源 | 全市场5586方案/2963证券、12全代理请求、全链路集合内容一致/pending0、六清理通过 | `py scripts/verify_repurchases.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --proxy-only --output out/source-1.json --timeout 1200` exit0；[新来源原报告](architecture-e6f-source-2026-10-21.json) |
| E6f容量 | 原50000行真实测量通过，完整内容一致/重复0DML/单修订1行/六清理通过 | 新measure_repurchases.py/repurchase_capacity.py保留原50000行/全部原阈值；显式本轮source-proof，实际server UUID、UUID owner/锁、会话SQL守卫、取消settle及最终清理，拒绝覆盖报告 |
| T3 | 第三轮完整18/18通过，首两轮失败保留 | 同原完整measure命令，新输出out/t3-3.json，exit0；[最终T3](architecture-e6f-t3-final-2026-10-21.json)，正确性/可比性/cleanup通过 |
| M文档 | 正文及coverage已同步，开发文档35项通过；发布前最终审阅在当前正文定稿后执行 | 来源说明、包README、程序内回购和MySQL归属、状态及证据；无DDL，字段字典/数据库设计保持 |
| A4/U1～U3 | 未发布、未验收 | 必须完整唯一verify-release后，同包真实查询/桌面/启停/草稿/滚轮/窄窗/帮助/正常关开、两config及48保存设置/原偏好保持 |
| A1～A3 | 发布保护未修改，无新增破坏性演练 | 完整正式门禁仍必须执行相关反例 |
| M1/F类型与成本实验 | F专属未开始 | 不借本批测试宣称完成 |

## 真实来源适用性与限制

在请求前登记：本批正式来源/解析/执行/消息/恢复无实质变化，五模块等价证据和回购专项支持纯组织迁移。回购按REPURCODE全市场方案集合遍历，不按股票过滤；替代验证为整轮所有可见方案、全部正式分页与详情、集合及每列内容，并保存代理次数与本轮pending0。此范围不宣称随机30股票或严格历史信号回放通过，不将来源当前版本变成单一时点快照。历史H3空名债券/E4严格来源/资本准备限制保留。

新来源工具不写生产业务/站点/任务配置，在私有实例SQL/Redis执行原collector与统一归档，临时观测只保存统计/摘要与一个容量代表方案，不保存成功响应全集。容量要求当前源码来源报告已通过、全代理、清理完成、集合一致，不以文件存在代替有效证据。

## 失败与资源交接

初次公共命令误列不存在的tests/test_ingest.py，exit4且未执行测试；更正为实际正式专项。一次额外strict命令误选未纳入既定strict范围的5文件出现29条原有未标注错误，未改类型要求或掩盖失败；正式配置的mypy八文件已exit0。ruff check .误扫描历史pytest故意损坏TOML失败；改用正式src/scripts/tests范围，发现两处迁移后导入排序待修。以上均不是通过证据。

Empire1316790已Alt+F4正常关闭，界面显示保存进度/结束归档/关闭连接，随后窗口枚举无Empire。结束必须重开。自有13348继续运行供本批，不关生产库/共享Redis、不删他人锁/数据、不清未解决错误。实际发布身份、远程及同包桌面待完成后补录。

最终正式Ruff范围`py -m ruff check src scripts tests`已exit0，两处测试仅导入排序修正。strict使用pyproject既定八文件`py -m mypy`exit0；未扩展F的类型范围。完整来源输入摘要e305262a07da615fc7d247a426837841e552436ce8dc51b7992d3fc98cc059e6；原collector/统一归档/全5586方案列表与详情以及全SQL规范集合逐列一致，五基础preparation通过，temporal=fail但analysis用途nonblocking，保持原严格历史限制。

[当前容量绑定扫描](architecture-e6f-capacity-binding-scan-before-2026-10-21.json)仅repurchases.page四绑定失效，正在真实重测；其他当前measured报告无变化。初始[资源核查](architecture-e6f-preflight-resource-2026-10-21.json)、[前像](architecture-e6f-preimage-2026-10-21.json)和[五模块等价](architecture-e6f-organization-equivalence-2026-10-21.json)均来自本轮实际执行。

容量实际命令`py scripts/measure_repurchases.py --test-settings build/architecture-evolution-20261019/mysql-settings.json --source-proof out/source-1.json --output out/capacity-1.json`exit0，报告[新容量](architecture-e6f-repurchase-capacity-2026-10-21.json)。原查询、规模、10次最大值及全部预算保持，增加实际UUID/owner/SQL守卫、全行内容核对和原样本证据检查；不改旧数字/hash。设计卡已指向新报告。

T3第一轮`py scripts/architecture_benchmark.py measure --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output out/t3-1.json`exit1，17/18；holders_detail.p95=8.37423ms>6.1948125ms，一个样本15.9175ms，其余2.7348～5.1414ms；正确性及清理通过、incomparable空。原报告[首失败](architecture-e6f-t3-first-2026-10-21.json)保留，尖峰根因未证明，不能据此宣称原性能已通过；等待独占空档全轮复测。

T3第二轮同一完整命令改新输出out/t3-2.json，exit1、17/18：前轮持有人详情通过，news_search.p95=25.65655ms>17.8190125ms，一个样本59.1806ms，其余8.5825～11.2891ms；正确性及清理保持通过，无不可比项。[第二轮失败](architecture-e6f-t3-second-2026-10-21.json)保留，不能合并两轮的通过子项冒充整轮通过。测量后只读实核13348为原UUID、仅四系统库/无其他客户端；正在测量前记录环境CPU并等待空档。尖峰原因仍未证明。

T3第三轮前实测10秒进程CPU快照（out/ambient-cpu-before-t3-3.json）未见同期测试/构建主导负载，等待30秒空档后完整重测，exit0、18/18；不是从首两轮挑通过子项。首两轮单次延迟尖峰根因未证明，所有报告与原样本保留。基线、工具、协议、阈值及release_lock原字节保持。

最终文档动作：回购源说明与程序内回购数据/SQL归属逐项同步、coverage迁移、原存储字段和用户行为保持。最终审阅采用`documentation_contract.py review --note <回购五模块与安全实采/容量的具体审阅说明> --unchanged-reason <其他业务与共享服务未改的具体依据>`；此前同命令及设计/架构/装配均exit0，35文档专项/25.71秒通过，当前定稿后再建立最终审阅并核门禁。
