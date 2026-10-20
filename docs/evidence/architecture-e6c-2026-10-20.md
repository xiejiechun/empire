# E6c 更名与ST事件实施记录

当前状态：**开发验证通过，待正式发布及同包真实桌面**。不进入E6d。前批E6b-aliases结案提交`82aa0232d452b58169cb6a5d92305ef65a6783e7`已在前批push并精确核实；本次接续远程复核暂因GitHub 443连接失败，不能据此重新声明已同步。当前安装仍为实现`b96abe2`、release `e50fe39d6083405ab7abaf86d90a2561`。

## 范围、前像与退役

从当前正式前像重建，未应用整份E草稿。`contracts/name_changes.py`、`contracts/st_events.py`及各自原collector/source/dataset/data/UI共12模块迁入`features/name_changes`、`features/st_events`的contract/source/collector/dataset/query/ui。旧文件删除，脚本与测试调用方、coverage、架构和装配映射同步；两bundle从remaining接回原槽位，builtin仅增加两个工厂。公共EventTimeline、QueryScope、preparation、下载/代理/频控/预取/入队/归档/摘要/调度保持原唯一路径。

本批无DDL，不执行生产采集、迁移或数据清理。四个项目/任务、插件、数据集、schema、namespace、页面及顺序保持；原名称组合、来源出现次数、原因、空名、历史旧代码、迟到旧响应保护和成功清队语义保持。12份非import AST完全相同；这只证明组织等价，不能代替链路与桌面验收。

`collect_name_changes.py`与`collect_st_events.py`退役原默认生产写入流程，改为显式私有MySQL/Redis完整来源验收CLI，经共享`source_verification`/`PrivateStorage`核实际UUID、资源owner、逐会话SQL守卫、取消及独立清理。两份容量CLI共用`event_capacity.py`，保持原25000事件/SQL/20次计时与阈值；容量为直接dataset SQL协议，不能冒充一次入队容量。

## 适用验收与初步证据

本批输出目录`<out>`为`build/architecture-e6c-20261020`，`py`为项目`.venv/Scripts/python.exe`，测试配置为已核实自有13348的`build/architecture-evolution-20261019/mysql-settings.json`。测试实际UUID为`a3e8a5eb-cb64-11f1-8ddf-380525361d4e`，与生产3307不同；所有凭据及owner原文仅在ignored目录。

| 验收ID/范围 | 实际命令、退出码与证据 | 当前结果、限制及剩余工作 |
| --- | --- | --- |
| C1/C2身份顺序 | `py scripts/assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json` exit0 | 实际装配通过；首轮将4个非装配模块放入映射而被拒绝，移除unused映射后通过，未放宽门禁 |
| C3/C4组织/退役 | `py scripts/architecture_contract.py check --output <out>/architecture.json` exit0；`<out>/preimage.json`及`equivalence.json` | 399模块/1444导入/0新增债务/45退役，1条既有债务保持。最终静态/类型及退役复核待做 |
| R1～R3、安全/隔离 | `EMPIRE_INTEGRATION=1`、显式测试配置；`py -m pytest tests/test_event_verification_tools.py tests/test_source_verification.py tests/test_name_changes.py tests/test_st_events.py tests/integration/test_name_archive.py tests/integration/test_st_archive.py --basetemp build/pytest-e6c-final-sql -q --junitxml <out>/safety-sql.xml` exit0 | 181 passed/137.01秒，无skip；真实私有SQL/Redis归档与清理，来源bytes使用fixture不计实采。补全容量端到端回归的第二轮正在运行 |
| R2完整来源 | `py scripts/collect_name_changes.py --test-mysql-settings <测试配置> --proxy-only --output <out>/names-live-1.json`与对应`collect_st_events.py ... --output <out>/st-live-1.json`均exit0 | 每栏目1次共享代理、direct/fallback0；公司3579源条→3549规范事件（出现次数保留）、股票8366、实施2590、撤销1361，三市场集合/内容、SQL证明和正式全分页一致，pending0，六清理true，无残留。工具/正文修改后最终源码绑定需重验 |
| R2来源用途限制 | 上述两份真实报告preparation逐项原值 | 公司缺名68/断链22，股票缺名124/断链17；历史temporal为非阻断fail，未改写通过。ST不裁定每日状态/公告可用日。非逐股票请求，随机30股N/A且sample_30_met=false；不裁剪当前股票名单 |
| 容量/资源7～8节 | `py scripts/measure_name_changes.py --test-settings <测试配置> --output <out>/names-capacity-1.json` exit1 | SQL守卫拒绝未经覆盖形式，未获得测量；六清理true、无残留。根因为新metadata参数名`table`触发保守SQL形式检查，改为现有正式形式`object_name`，不放宽共享守卫；新增双family完整measure私有回归，待结果。两份最终新测量未完成 |
| R4公共路径 | 待实际运行公共归档/预取/调度/装配回归 | 单完整响应无独立后页分页；三市场一次原子入队后才等待归档，不人为增加请求或逐市场等待 |
| T3 | 原冻结协议、原基线及原工具 | 未开始；待最终源码、独占环境测18项，不能复用前批结果 |
| M文档、A1～A4、U1～U3 | 最终review/文档专项、唯一正式门禁及同包真实桌面 | 未完成；包含四页面、帮助、启停/草稿/滚轮/窄窗、48保存设置与原config/偏好、异cwd连接/正式查询及正常关开 |

正常桌面已在开工前退出，未强杀或删除锁；验证结束必须重新打开。H3固定空名债券、E4严格来源、资本历史准备及生产历史freshness/旧错误`38622b7215a44fe4a5224031bdf4d963`仍未解决，不清理或抵销。整个优化未完成。

## 最终开发验证（上述首轮之后）

| 验收ID | 实际命令、退出码与最终证据 | 结果及限制 |
| --- | --- | --- |
| R1～R3/资源 | 同上181项清单，`--basetemp build/pytest-e6c-final-sql-2 --junitxml <out>/safety-sql-2.xml` exit0 | 181 passed/149.64秒，无skip。新增实际执行两family完整25000行measure（包括metadata查询），再走正式collector/归档/查询及清理，修复参数名而未放宽SQL守卫 |
| R4/C/U公共回归 | `py -m pytest tests/test_name_changes.py tests/test_st_events.py tests/test_archive_queue.py tests/test_fingerprint_versions.py tests/test_ingest_reservations.py tests/test_unit_prefetch.py tests/test_prefetch_budget.py tests/test_all_collector_prefetch.py tests/test_collection_control.py tests/test_manager.py tests/test_feature_bundles.py tests/test_dataset_contributions.py tests/test_assembly_contract.py tests/test_assembly_order.py tests/test_assembly_source_gate.py tests/test_architecture_contract.py tests/test_ui_architecture.py tests/test_ui_architecture_counterexamples.py tests/integration/test_preview_queries.py --basetemp build/pytest-e6c-public -q --junitxml <out>/public.xml` exit0，集成显式启用 | 379 passed/37.81秒，无skip；共享预取/入队/隔离/成功清队、原顺序及真实私有SQL预览查询保持 |
| 静态/类型/退役 | Ruff检查两包、受影响脚本及测试exit0；`py -m mypy` exit0；architecture最终、assembly snapshot/check同上exit0 | strict已登记8文件通过；[12模块等价](architecture-e6c-equivalence-2026-10-20.json)与[实际前像](architecture-e6c-preimage-2026-10-20.json)，原职责函数非import AST相同。只修正四条rules.json source_file，不改变其参数/来源/生命周期 |
| R2最终来源 | `py scripts/collect_name_changes.py --test-mysql-settings <测试配置> --proxy-only --output <out>/names-live-3-final.json`及`collect_st_events.py ... --output <out>/st-live-3-final.json`均exit0 | [更名](architecture-e6c-names-source-final-2026-10-20.json)、[ST](architecture-e6c-st-source-final-2026-10-20.json)绑定最终源码；公司3549/股票8366/实施2590/撤销1361规范事件，四次全代理、内容集合相同、pending0、六项清理true，无SQL/Redis残留。普通用途与历史temporal失败分开，仍不满足股票30样本门槛 |
| 容量 | 两`measure_*.py --test-settings <测试配置> --output <out>/names-capacity-3-final.json`、`<out>/st-capacity-2-final.json`均exit0 | [更名](architecture-e6c-names-capacity-final-2026-10-20.json)2.1442秒/覆盖P95 156.1123ms/14303232字节；[ST](architecture-e6c-st-capacity-final-2026-10-20.json)2.4351秒/161.3991ms/15368192字节。原25000/5000证券/5日期/SQL/20次/全部limits不变，全25000集合内容与修订核对、重复DML0/修订2、环境及EXPLAIN、清理完整。四设计卡引用真实新测量，旧报告未刷新hash |
| T3 | `py scripts/architecture_benchmark.py measure --protocol docs/evidence/architecture-performance-protocol-2026-10-19.json --test-settings <测试配置> --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output <out>/performance-3-final.json` exit0 | [最终报告](architecture-e6c-performance-2026-10-20.json)18/18、无不可比项、correctness/cleanup通过。首轮通过后规则路径修正；第二轮新闻首页P95 61.8649ms超9.8253ms，[失败报告](architecture-e6c-performance-failed-2026-10-20.json)全样本保留（前4项38～67ms，后续4～6ms）；未发现同期Empire测试/发布，具体噪声原因未证实，不归因用户模式变化。未修改源码/工具/基线/阈值的下一次完整原协议重测通过；不删慢样本或拼接报告 |
| M说明 | `documentation_contract.py review`显式四页面不变理由及其余共享可达性说明、`check`、`verify_documentation.py`均exit0；`py -m pytest tests/test_collection_rules.py tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py tests/test_storage_help.py --basetemp build/pytest-e6c-docs -q --junitxml <out>/docs.xml` exit0 | 46 passed/24.90秒；246文档/1662链接。首轮review发现四规则旧source_file，修正后逐页面登记原行为不变，未用无关正文或泛化理由遮盖；最终再review。数据库设计55表/49数据集/12JSON通过 |

`py <out>/pre_release.py` exit0，当前preparation/source摘要`f330577ebfcd43d3cb7d28740ebd42b5d2ded5749708d4e5beb95d2f7827d17f`，两最终来源及容量均匹配（T3按其独立source_identity核实，不混用hash口径）。两config及原偏好保持，48行app_setting全部payload/updated_at及原偏好私密快照已保留。完整发布、同包真实桌面及最终push仍待执行，不能称已验收。
