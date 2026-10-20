# E6a 同花顺资本运作实施记录

状态：**已验收（本批组织迁移范围）**。正式release `7d92659ce1604c3a918e4317f4f7caa6`、干净实现提交`4550a9e43e3b83019ee534da472ea4dc4beef9a2`已完成完整门禁与同包真实桌面；结案文档随后提交推送。下文开发中“尚未”均保留为历史检查点，最终事实见末节。前批E5结案 `4e1dc72904925f9ba7d875f1db7e35f312c67421` 已实际push main并以ls-remote精确核实；本轮从该干净前像开始。E5正式包05630406和自有13348实际UUID/datadir/仅四系统库、冻结工具已只读复核。08:33前后正式窗口正常Alt+F4关闭，fresh窗口枚举为空；此前45任务/活动0/pending0/既有失败5。没有其他测试、发布、实采或维护，结束需重开。

## 实施前范围及验收登记

六旧模块按正式迁移清单进入`features/ths_capital`的contract/source/collector/dataset/query/ui；从remaining取走原500/600/700插件、400任务、100数据集槽位。全部调用方、测试patch、显式建表维护入口、工具、覆盖和结构说明同步迁移；不留转发层。公共HTML仍为`sources/html.py`。实际前像另发现`capital_transport`只服务本业务、直接导入本业务字段，却误归capital_actions；本批补迁为`ths_capital/transport.py`，第七旧入口同步退役，正文及schema2不改。该项为正式源码核实后的清单补充，不创建重复路径。

E0 `sql/business-schema.json`已登记本数据集八表，业务TABLES改为读取该唯一表组；专项验证原顺序与字段规格精确对应。SQL结构、schema2、插件/能力/任务/job/dataset/namespace/page及用户设置均保持，不执行生产DDL或数据迁移。

请求前适用性：这是业务组织与既定表组权威接线，来源解析/参数/完整性/修订/断点/恢复正文不改。任何实质变动撤销纯迁移判断并执行适用随机30+固定回归；不在失败后换样。本轮仍计划使用冻结seed20261020的随机30及既有失败证券固定回归，取得九栏目当前来源→入队→归档→正式列表/详情/审计集合与内容证据；来源缺口或准备失败独立保留，不由组织等价冲销。

旧`verify_ths_capital.py`会按显式配置写库、重置范围并可能保存任务默认值，缺少实际UUID/逐连接SQL守卫/共享私有清理；不得直接运行。先改为共享source_verification/PrivateStorage，再验证观察器、随机样本、实际私有SQL正向smoke、拒绝与取消清理，之后才请求来源。生产只读池/设置与共享代理目录之外，写入仅UUID私有资源。

适用矩阵：C1/C2精确身份顺序，C3/C4旧入口退役；R1～R4九栏目、空值/单位/货币、同数异集、旧响应、冷热摘要、SQL后重放和独立归档/取消；E6a新容量绑定实际工具/业务/SQL权威，保持700证券原协议阈值；T3冻结九指标18项；M说明/覆盖/最后review；A4唯一完整发布及U1～U3同包真实窗口、配置/设置/偏好及正常关开。A1～A3保护实现未变，不重复破坏性演练。任何适用项缺失不得进入E6b。

## 证据与资源

本机输出目录`build/architecture-e6a-20261020/`。自有13348继续运行供本批，生产3307/共享Redis不重启，不清未解决错误或业务数据。E5远程实核记录`build/architecture-e5-20261020/remote-close.json`；本批只读前检`preflight-resource.json`。正式实现、开发、来源、容量、性能、发布、桌面及远程结果按实际执行追加，当前均不得预写通过。

## 当前开发验证

实际源码已按当前前像逐文件核对后迁移，七旧入口删除，无兼容转发。领域专项命令为 `.venv/Scripts/python.exe -m pytest -q --tb=short tests/test_ths_capital.py tests/test_ths_capital_lifecycle.py tests/test_ths_capital_transport.py tests/test_ths_capital_ui.py --basetemp build/pytest-e6a-domain --junitxml build/architecture-e6a-20261020/domain.xml`，exit0，521 passed/4.27秒。

安全及实际私有SQL命令为设置 `EMPIRE_INTEGRATION=1`、`EMPIRE_TEST_MYSQL_SETTINGS=build/architecture-evolution-20261019/mysql-settings.json` 后运行 `.venv/Scripts/python.exe -m pytest -q --tb=short tests/test_ths_capital_verification.py tests/test_source_verification.py tests/test_capacity_session.py --basetemp build/pytest-e6a-safe-sql-2 --junitxml build/architecture-e6a-20261020/safety-sql-2.xml`，exit0，130 passed/5.61秒。含实际UUID私有SQL、两只合成证券九栏目正式采集/入队/统一归档/列表/全部详情、守卫及六项清理；无真实来源请求。首次`safety-sql.xml`为129 passed/1 failed，测试构造Envelope遗漏run_id/batch_id，补参数后重跑通过，原失败保留。

归档/预取命令为同样显式独立服务环境运行 `.venv/Scripts/python.exe -m pytest -q --tb=short tests/integration/test_ths_capital_archive.py tests/integration/test_prefetch_pipeline.py --basetemp build/pytest-e6a-integration --junitxml build/architecture-e6a-20261020/integration.xml`，exit0，16 passed/76.72秒。来源、容量、T3、最终文档、正式发布及真实桌面均尚待执行，不能以这些开发结果代替。

## 最终开发证据

| 适用项 | 实际命令与输入 | 退出与证据 | 范围及限制 |
| --- | --- | --- | --- |
| C1/C2/C3/C4 | `py scripts/architecture_contract.py check --output build/architecture-e6a-20261020/architecture.json`；`py scripts/assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json`，另snapshot | 全部exit0；388模块/1424导入，4既有债务/0新增/43退役，精确身份语义顺序匹配 | 七旧模块退役、无双路径；[正文等价](architecture-e6a-equivalence-2026-10-20.json)仅排除导入和TABLES赋值，后者另以SQL权威及字段顺序精确验证，不代替行为验收 |
| 公共R1～R4 | `py -m pytest -q --tb=short tests/test_archive_queue.py tests/test_fingerprint_versions.py tests/test_ingest_reservations.py tests/test_unit_prefetch.py tests/test_prefetch_budget.py tests/test_all_collector_prefetch.py tests/test_collection_control.py tests/test_manager.py tests/test_assembly_contract.py tests/test_assembly_order.py tests/test_assembly_source_gate.py tests/test_architecture_contract.py tests/test_shared_boundary_injection.py tests/test_ui_architecture.py --basetemp build/pytest-e6a-public --junitxml build/architecture-e6a-20261020/public.xml` | exit0，283 passed/25.17秒 | 与前述521领域/130安全SQL/16隔离共同覆盖；完整发布尚未运行 |
| 静态/类型 | `py -m ruff check src tests scripts`；`py -m mypy` | 均exit0，8公共边界严格类型通过 | 冻结工具和阈值保持 |
| 当前真实来源 | `py scripts/verify_ths_capital.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --output build/architecture-e6a-20261020/source-1.json --random-count 30 --seed 20261020 --proxy-only --timeout 1800` | exit0，38股票/5080事实；38代理，direct/fallback0；来源/入队/SQL八表/所有列表页/全部详情/解除关联/范围审计集合内容一致，pending0，六清理true、残留false。[脱敏有界报告](architecture-e6a-source-2026-10-20.json) | 正式池5579，随机30+八固定不换样；私有实例a3e8a5eb-cb64-11f1-8ddf-380525361d4e。九栏身份/字段/质量/覆盖等检查通过，temporal全部保留非阻断fail：报告期不是公告日，当前正文含后续进展，不提供严格历史版本回放。不能宣称严格历史信号可用或生产全池采完 |
| E6a容量 | `py scripts/measure_ths_capital.py --test-settings build/architecture-evolution-20261019/mysql-settings.json --report build/architecture-e6a-20261020/ths-capital-capacity.json` | exit0，700证券/10500事实，导入19.028秒，重复业务DML0，列表/详情/窗口上界2.608/0.973/3.556ms，审计1673.390ms，分配20070400字节；六项清理通过。[新测原报告](architecture-e6a-capital-capacity-2026-10-20.json) | 原样本、预算不改；新绑定实际迁移后代码、transport、SQL权威/loader及工具，不刷新旧hash |
| T3 | `py scripts/architecture_benchmark.py measure --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output build/architecture-e6a-20261020/performance-1.json` | exit0，九指标median/p95共18/18，incomparable空，清理完成。[原报告](architecture-e6a-performance-2026-10-20.json) | 测量时无同期测试/来源/容量/构建/桌面；原协议、工具、基线和阈值不改；非网站吞吐或真实桌面性能 |

当前下一步为最后文档审阅及相关检查，之后实现提交、唯一正式发布与同包U1～U3。此前H3/E4来源失败、资本历史准备限制、停复牌未解决错误均保留，未做错误清理或生产DDL。

### 最后审阅发现与修正

首次文档review exit1，采集规则资源`rules.json`仍指旧collector路径；补迁该一处静态登记后第二次review精确指出八表和preparation-report正文未变。逐项复核DDL、字段/索引、写入/版本/清理及报告物理键契约无变化，使用九条明确`--unchanged`理由登记，而非修改无关正文。最终review/verify_documentation/verify_database_design均exit0（233文档/1592链接，55表/49数据集/12 JSON）；文档与规则四文件回归41 passed/24.91秒，`docs-final.xml`。首轮source-1和performance-1发生在规则路径修正前，保留为早期输入证据，最终当前输入重新执行source-2与performance-2，不能直接复用旧身份。

### 当前输入复核及发布前冻结

采集规则路径修正后，以上真实来源命令仅将output改为`source-2.json`完整重跑，exit0；同一池5579、相同seed和全部38只（随机30+固定8）、5080事实、38代理/direct及fallback0，所有正式查询集合/内容一致、pending0，清理全部true/残留false。[最终来源报告](architecture-e6a-source-2026-10-20-2.json)保留九栏非阻断temporal限制。

T3同一正式命令output改为`performance-2.json`，exit0，18/18通过/incomparable空，原协议阈值不变。[最终T3报告](architecture-e6a-performance-2026-10-20-2.json)与当前source_identity精确一致。新容量绑定仍有效；没有仅刷新旧报告hash。新增补充命令为显式独立服务环境 `py -m pytest -q --tb=short tests/test_feature_bundles.py tests/test_dataset_contributions.py tests/integration/test_archive_fairness.py --basetemp build/pytest-e6a-exit --junitxml build/architecture-e6a-20261020/exit-regression.xml`，exit0，49 passed/56.71秒。

发布前核对source-2当前源码摘要、T3当前产品摘要、全部原config/偏好hash保持；只读保存48行设置payload/updated_at供同包桌面后精确比较。实现提交后不修改受保护输入或Git HEAD，唯一正式门禁自然结束前只在ignored build准备审阅工具。当前尚未正式发布或桌面，不能进入E6b。

## 正式发布、桌面与逐项结案

唯一正式命令`./verify-release.ps1`使用显式`EMPIRE_TEST_MYSQL_SETTINGS=build/architecture-evolution-20261019/mysql-settings.json`和独立pytest临时目录，自然exit0；24步骤及受控安装切换成功，journal为committed/passed。原JUnit复核3773 passed、5 opt-in skipped、20 warnings，2175.30秒；五跳过均为未改动的state-unit显式演练，不计入通过。模板缺配置步骤按预期exit1，其余步骤exit0。发布期间HEAD及1570完整输入冻结，54保留输出逐项复核，无输入失配。[机器审阅](architecture-e6a-release-audit-2026-10-20.json)保留原actual_desktop进行中字段，不倒改旧报告。

完整输入`b5081a0161f78219b49b0ba624eca1b27d9ae49bec6f4c9654edae0ac067c740`；EXE `ff639a86d64fbd0a57c522ce899c2109247d26f60421c3c76a84399ac0667d1a`；安装树`3bbacf33f9cfc75898de24fad3e7f08afa0456ea64e725e9b3231bef29e1dba3`。发布后和正常关闭后两轮机器核验均exit0，同包配置/偏好、异cwd真实连接和正式查询精确比对通过，见[关后报告](architecture-e6a-post-release-2026-10-20.json)。

| 验收ID | 适用范围及最终结果 | 实际证据与限制 |
| --- | --- | --- |
| C1/C2 | 通过：插件、任务、数据集、页面、schema和六类顺序保持 | 精确装配及49补充回归；完整发布再次验证 |
| C3/C4 | 通过：七旧模块及全部当前调用方退役，唯一业务路径 | architecture/assembly、正文等价和迁移清单；历史evidence不重写 |
| R1 | 通过：重复无DML、修订、旧版、冷热摘要及SQL提交后重放/成功清队 | 521领域、16隔离、130安全SQL、283公共及完整门禁 |
| R2 | 通过：九栏目来源业务键/内容、同数异集/空值/单位和关联 | 最终source-2随机30+固定8/38全代理/5080事实，pending0、六清理true；temporal非阻断失败仍保留 |
| R3/R4 | 通过：取消清理、按序入队、归档独立与整轮末确认 | 生命周期/预取/归档专项及49补充；不新增下载、队列或调度 |
| H1 | 适用共享HTML边界通过 | 资本复用公共sources/html，未反向依赖持有人；H2/H3持有人来源未改，本批不重复，既有H3 FAIL不冲销 |
| E6a容量 | 通过：当前迁移后真实新测与绑定 | 700证券10500事实，原预算，重复DML0，清理通过 |
| T3 | 通过：最终当前输入18/18 | performance-2；旧首轮保留；原工具、协议、基线和阈值保持 |
| M文档 | 通过：业务说明/结构/覆盖/采集规则与最终review | 发布前41文档回归及门禁；结案文档另审，不冒称进入原冻结包；F的M1定位演练等仍未完成 |
| A4/U3 | 通过：唯一正式发布与同包身份/设置 | 24步骤、包清单/EXE/tree、48行payload与updated_at及原config/偏好保持 |
| U1/U2 | 通过：真实启停依赖/草稿/栏目/分页/滚轮/窄窗与帮助 | [真实桌面](architecture-e6a-desktop-2026-10-20.md)，914×892实窗和长正文滚动；仅覆盖记录范围 |
| A1～A3、D1～D3 | 实现未改；相关回归随完整门禁通过，额外破坏性现场演练不适用 | 不重复中断发布或关闭生产服务；不把旧诊断partial改为通过 |

`.venv/Scripts/python.exe build/architecture-e6a-20261020/close_desktop_settings.py`于10:02正常退出后exit0，[精确设置核对](architecture-e6a-settings-restored-2026-10-20.json)记录全部48行payload/updated_at、两config及原偏好摘要保持。10:03重开正式工作台987020，连接正常、活动0/pending0/既有失败5。最终只读资源脚本exit0，13348实际UUID/datadir保持、仅四系统库且无其他客户会话；无本轮私有资源残留。未清未解决错误或业务消息，未重启共享Redis/生产库。

E6a本批适用出口已满足，结案提交及push/ls-remote完成后才开始E6b。资本temporal/历史准备限制、持有人空名债券H3、E4严格来源失败及停复牌精确错误继续保留，不能解释为整个优化完成。E6b～g/F仍待实施。

结案文档检查：review、documentation_contract check、verify_documentation、verify_database_design及git diff --check均exit0（234文档/1600链接，55表/49数据集/12 JSON）。首次回归命令误写不存在的单数test_documentation_contract.py，exit1/no tests ran，未计为验证；核实现有四文件后以tests/test_documentation_contracts.py、test_documentation_sources.py、test_documentation_review.py、test_collection_rules.py重跑，docs-close-3.xml，exit0，41 passed/26.58秒。
