# E6b-status 上市状态实施记录

状态：**本批组织迁移范围已验收，结案提交待推送核实**。实现230c5d206c3407d97cd568032dc40b398c0450f1、唯一正式发布dad5a84751e44fe1a6f35ef4e577c7b0及同包真实桌面均完成；六固定月份来源链路通过，生产历史freshness失败原样保留。前批上市子批实现fec74bc/release a2382f71已完成同包真实桌面、结案13421f29fd145b2e6c23d01677f48c7e0874398b推送并ls-remote精确核实。以下开工与开发过程保留历史时态：开工工作区干净，安装保持前批包；11:47前后工作台45/活动0/既有失败5/pending0，Alt+F4正常关闭。未启动子代理。

## 请求前范围与验收登记

仅迁移七模块：contracts/listing_status→features/listing_status/contract；collectors/tdx_listing_status_source→source、tdx_listing_status→collector；datasets/listing_status→dataset；data/listing_status→query、listing_status_checks→audit；ui/listing_status→ui。valid_proof与FINGERPRINT_VERSION移至contract，原函数体/版本不变，dataset/query使用唯一公共契约。新增bundle、init及定位README；仅从remaining移出插件7700/7800/7900、任务1900、数据集2200原声明。调用方、动态patch、显式维护、规则和覆盖同步；不留转发层、双登记或旧入口。

保持项目tdx-listing-status、job tdx-listing-status-v1、dataset listing_status.month、schema1、摘要tdx_listing_status_v1、security_listing_event及月内完整身份/说明、用户保存配置。无DDL/业务数据迁移，不改变来源参数、过滤/分页/日期、生命周期或UI行为。空月仍须合法每日响应和完整月份证明，未知不能变空。

适用C1～C4精确身份/顺序/退役、R1～R4三类事件/同数异集/过滤/修订/冷热摘要/SQL后重放/恢复取消及独立归档、原50000事件容量新测、T3原18项、M文档/规则/覆盖最后review、A4正式门禁及同包U1～U3。A1～A3保护实现未改，额外破坏性演练不适用。来源按日完整市场响应、不按当前股票池或证券请求，随机30股不适用；须对固定完整月份1990-12、1999-07、2020-05、2021-08、2022-04、2024-07逐日来源→规范化→入队→SQL→正式分页/详情/月份证明逐项集合内容比较，全代理/pending0。保留盐湖暂停/恢复、琼民源终止等历史反例；有限月份不冒充全历史或重新上市完整。

旧verify_listing_status会写生产、旧measure_listing_status仅host/port检查且清理前落盘，均不执行。先复用PrivateStorage/source_verification实现实际server_uuid、UUID库/namespace、owner及同连接锁、逐连接SQL守卫、取消等待/独立清理与PASS在清理后的流程。容量只领域子类精确允许本表ANALYZE与原固定EXPLAIN/EXPLAIN ANALYZE，不放宽共享守卫，保持50000行/原分布/原50ms等预算。来源/容量工具必须先专项与真实私有SQL正向验证再运行。

当前准备目录build/architecture-e6b-status-20261020，prepare_migration.py从实际源码构建30项精确前像/候选，旧路径前像保存；未整树套E草稿。最初把七模块误计为八，准备器在写入前拒绝，纠正计数后完成；没有正式源码变更由该失败产生。

H3空名债券、E4严格来源失败、资本历史准备限制、停复牌旧精确错误继续保留，不按本次组织迁移清理。尚待实际实现、开发/来源/容量/性能、正式发布与同包真实桌面；不能进入aliases。


七旧入口已实际迁移，30项前像校验后应用。valid_proof/版本保持原体并集中contract，数据集协议显式导出同一版本对象。首次领域测试暴露动态import拼接旧路径，修正后精确装配及108领域/预取回归exit0；架构392模块/1431导入、2既有/0新增/45退役债务。首次无效source角色与多余assembly helper映射均被工具拒绝，改为原source_adapter及仅四贡献模块精确映射后通过；未改变工具使其宽容。安全工具103 passed/1 opt-in skipped，真实私有SQL正向另执行；不计跳过为通过。


## 实际执行结果（尚未发布）

全部使用.venv/Scripts/python.exe。领域命令：`py -m pytest tests/test_listing_status.py tests/test_listing_scope_prefetch.py tests/test_all_collector_prefetch.py tests/test_feature_bundles.py tests/test_assembly_order.py --basetemp build/pytest-e6b-status-unit-2 --junitxml build/architecture-e6b-status-20261020/unit.xml -q`，exit0，108 passed/1.37秒。安全命令：`py -m pytest tests/test_listing_status_verification.py tests/test_source_verification.py --basetemp build/pytest-e6b-status-safety --junitxml build/architecture-e6b-status-20261020/safety.xml -q`，exit0，103 passed/1 opt-in skipped/1.70秒。显式EMPIRE_INTEGRATION=1及独立13348配置，`py -m pytest tests/test_listing_status_verification.py tests/integration/test_listing_status_archive.py tests/integration/test_prefetch_pipeline.py --basetemp build/pytest-e6b-status-integration --junitxml build/architecture-e6b-status-20261020/integration.xml -q`，exit0，21 passed/67.69秒。跳过的真实私有SQL正向已在这轮实际运行，不算模拟来源实采。

`py build/architecture-e6b-status-20261020/check_equivalence.py` exit0，[正文比较](architecture-e6b-status-equivalence-2026-10-20.json)七模块除导入和明确移动符号外AST完全相同，valid_proof原体等价；不代替业务行为。ruff及严格mypy八公共边界exit0。

`py scripts/verify_listing_status.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --proxy-only --output build/architecture-e6b-status-20261020/live-1.json`，exit0，[初次有界报告](architecture-e6b-status-source-initial-2026-10-20.json)：六月份167请求全代理/direct及fallback0、26事件。来源/入队/SQL/正式分页详情/证明集合内容逐项一致，固定历史事件保留，六清理true、remaining.sql/redis=false、pending0。非股票来源，sample_30_applicable=false，不称30股通过；仅固定月份，不证明全历史或重新上市完整。随后仅容量脚本参数名修改，最终全输入来源证据仍需再执行。

容量命令 `py scripts/measure_listing_status.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --output build/architecture-e6b-status-20261020/capacity-1.json` exit1，原因是原查询绑定参数名table触发公共SQL守卫未经覆盖形式。仅build诊断包装同命令output改capacity-2-diagnostic.json再现exit1，打印拒绝SQL形状而不打印参数/连接。两次六项清理true、无残留，未计通过、未放宽公共守卫。测量器仅将参数名改为object_name；output=capacity-3.json再次真实执行exit0，[当前原报告](architecture-e6b-status-capacity-2026-10-20.json)：原50000事件/120月份/正文分布保持，逐行完整内容一致；列表/证券/后页/类型/详情/月P95分别2.376/0.889/2.890/2.743/0.980/3.358ms，导入12.350秒，分配48070656字节；重复written0、修订written1。原50ms/100ms/15秒/128MiB预算不变，全部通过、六清理true/无残留；新bindings、完整samples与实际实例/刷盘参数保留。未请求来源，不证明生产覆盖。


最后容量参数名修正后，同一实采命令仅output改live-2-final.json，再次全六月份exit0，[最终来源报告](architecture-e6b-status-source-2026-10-20.json)source_sha256与当前源码精确相符、167全代理/26事件/正式集合内容一致/pending0，六清理true/无残留。474公共领域通过/1 opt-in skipped/27.47秒，完整命令及JUnit为本机public-domain.log/xml；41文档与规则回归exit0/25.68秒。最后文档review首轮因page:listing_status正文未变而拒绝，逐项复核确为内部归属/契约位置改变、原用户筛选分页/详情和限制不变，以明确单page理由登记后通过；check、verify_documentation（239文档/1618链接）、verify_database_design（55表/49数据集/12 JSON）均exit0。未修改无关正文冒充同步。


T3命令 `py scripts/architecture_benchmark.py measure --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output build/architecture-e6b-status-20261020/performance-1.json` exit0、18项通过，但期间执行者短暂做了源码摘要扫描，该轮仅保留诊断，不作为独占性能验收。原命令output改performance-2-exclusive.json，停止全部来源/SQL/测试/扫描/构建后完整重测exit0，[独占原报告](architecture-e6b-status-performance-2026-10-20.json)九指标median/p95共18/18、无incomparable、cleanup=true，全部原样本与环境保留；没有修改harness/协议/基线/阈值。两config、偏好和冻结文件由preflight_resource.py只读再次核实exit0，实际13348仅四系统库/无其他客户会话，安装仍为上批包。

本批开发适用出口通过；最终事实文档审阅后形成实现提交，再执行唯一正式发布及同包U1～U3；此状态不能进入aliases或称已验收。


公共回归实际命令：`py -m pytest tests/test_listing_status.py tests/test_listing_scope_prefetch.py tests/test_listing_status_verification.py tests/test_source_verification.py tests/test_archive_queue.py tests/test_fingerprint_versions.py tests/test_ingest_reservations.py tests/test_unit_prefetch.py tests/test_prefetch_budget.py tests/test_all_collector_prefetch.py tests/test_collection_control.py tests/test_manager.py tests/test_feature_bundles.py tests/test_dataset_contributions.py tests/test_assembly_contract.py tests/test_assembly_order.py tests/test_assembly_source_gate.py tests/test_architecture_contract.py tests/test_shared_boundary_injection.py tests/test_ui_architecture.py tests/test_preview_redesign.py tests/test_preview_polish.py tests/test_preview_candidate_activation.py --basetemp build/pytest-e6b-status-final --junitxml build/architecture-e6b-status-20261020/public-domain.xml -q`；文档回归为`py -m pytest tests/test_documentation_contracts.py tests/test_documentation_sources.py tests/test_documentation_review.py tests/test_collection_rules.py --basetemp build/pytest-e6b-status-docs --junitxml build/architecture-e6b-status-20261020/docs.xml -q`，均exit0。

`py build/architecture-e6b-status-20261020/pre_release.py` exit0，最终来源摘要与当前输入精确相同、容量所有bindings未变、原两config及偏好保持；只读保存全部48行app_setting供发布后核验。冻结协议、性能工具、release_lock、DDL保持。最终review/check及文档/数据库门禁已通过；结案仍须同包配置/真实连接/正式查询及实际窗口，不以离屏结果替代。

发布前补充手册现行容量参数名与最终状态后，check明确拒绝正文审阅过期（exit1）；未提交或启动发布，重新审阅最终正文后再核验。最后完整开发文档检查结果为239文档/1620链接。

## 最终发布、真实桌面及验收矩阵

实现提交230c5d206c3407d97cd568032dc40b398c0450f1冻结后执行唯一 `.\verify-release.ps1`，自然exit0；发布dad5a84751e44fe1a6f35ef4e577c7b0的journal为committed/passed。完整24步骤（含构建、四档DPI、容量、搬移smoke、配置保留及正式切换），pytest **3786 passed / 5 opt-in skipped / 24 warnings / 2356.08秒**。五跳过均为独立state-unit显式opt-in演练，逐项理由保存在[发布审计](architecture-e6b-status-release-audit-2026-10-20.json)，不能计为通过。24 warnings包括release-entrypoint子进程读输出的4次UnicodeDecodeError线程警告，未删日志或改工具规避，pytest无失败。

`audit_release.py dad5a84751e44fe1a6f35ef4e577c7b0 230c5d206c3407d97cd568032dc40b398c0450f1` exit0：1598输入精确一致、54保留输出摘要核实、24步骤退出码核实。EXE SHA256 `b41d096259efc1a6aa5c82d1a4237d42ba47ef1375ef6521eddbe1c59b4adfa4`，安装树 `4f0286c52ca24b44ac66f86213029ac7c39199b867643fd3ab3b61a10a58e8cd`，包内source `d232a537fc154ce78bfe9604eac7c1edeaabc2ba641e04a7f95d7691a15c0985`。机器正式查询与实际EXE页面分开核验，没有把源码API冒充包内CLI。

| 验收ID | 本批适用范围、结果及证据 |
| --- | --- |
| C1/C2 | 精确插件/能力/任务/数据集/schema/页面/六类顺序；bundle及装配回归、正式门禁exit0；身份保持，无双登记 |
| C3/C4 | 七旧模块及全部调用方退役、valid_proof/版本唯一契约；架构0新增债务、精确等价及搜索通过；AST仅辅助，实际行为另验 |
| R1 | 重复无DML、修订/旧版、冷热摘要、SQL提交后重放、成功清队；21私有SQL/恢复与容量重复0/修订1及全量exit0 |
| R2 | 六完整月份167全代理、26事件逐项集合/内容/证明核对、固定历史事件与市场过滤反例保留；[最终来源](architecture-e6b-status-source-2026-10-20.json)exit0。逐日全市场响应，随机30股票N/A，有限月份不冒充全历史 |
| R3 | 有界月份预取/取消/归属/六项清理/独立实例反例，领域108、安全103及私有SQL21通过；一项安全opt-in后在隔离轮实际运行；不计跳过为来源验收 |
| R4 | 后批下载与前批归档独立、整轮末等待；prefetch专项、统一入队/归档/摘要公共474及全量通过；本轮私有pending0，无第二实现 |
| 容量 | 当前50000事件/120月完整内容及原预算新测exit0；[原报告](architecture-e6b-status-capacity-2026-10-20.json)。前两拒绝轮原样保留，不只刷新hash |
| T3 | 严格独占[18项原报告](architecture-e6b-status-performance-2026-10-20.json)exit0、cleanup=true，无不可比项。首轮有扫描干扰，仅诊断；冻结工具/基线/阈值未动 |
| M文档/规则 | 领域README、归属/设计卡/覆盖和内置说明逐功能审阅；行为不变理由明确，41相关回归exit0；结案最后review/check另执行。F的M1定位演练/M2/M3单源生成尚未实施，不由本批代替 |
| A4 | 同一完整正式发布exit0，journal、清单、输入/产物/依赖与保留证据核实；A1～A3保护实现未改，额外破坏性演练N/A |
| U1 | 页面单停不关采集查询，依赖阻止直接停query，collector单停拒绝原任务启动、历史查询继续，开关全部恢复；见[真实桌面](architecture-e6b-status-desktop-2026-10-20.md) |
| U2 | 真实列表/分页/盐湖暂停恢复说明、正常切页草稿、应用后结果、时间数字/下拉滚轮、任务草稿撤销、1047宽窄窗、帮助/限制实际观察完成。页面插件销毁会清临时筛选，明确区别 |
| U3 | 同包异cwd doctor真实连接、正式列表/详情/规划精确SQL比对、构建标识、48设置/原config及偏好保持、正常关开完成；[关后机器复核](architecture-e6b-status-post-release-closed-2026-10-20.json)、[设置](architecture-e6b-status-settings-2026-10-20.json)均exit0 |
| 资源恢复 | [资源核验](architecture-e6b-status-resources-2026-10-20.json)exit0；13348仅四系统库、实际UUID/datadir及无其他客户会话核实，测试/生产UUID不同。未停生产或共享Redis、未删未知锁/数据/旧错误 |

完整命令、退出码和产生时间对应[证据文件索引](architecture-e6b-status-evidence-index-2026-10-20.json)、原开发日志/JUnit及发布审计；本批报告为实际机器输出副本，未手写passed。桌面为106次带时间观察，正常关闭后恢复原偏好字节，14:59重开14682454可见、15:00构建身份/服务再次核实并留工作台可见；动态全局pending快照0不代表以后永远0。

限制：生产2020-05准备fields/keys/coverage/quality/temporal通过但freshness失败；这是原历史只读快照，不是本轮生产新采或全历史准备通过。H3空名债券、E4严格来源失败、资本历史准备及停复牌精确旧错误均保留。下一项仅在结案提交推送且远程精确核实后进入E6b-aliases；E6c～g/F及整个优化仍未完成。

结案文档最终核验：`documentation_contract.py review --note <本批结案具体说明>`、`check`、`verify_documentation.py`（240文档/1631链接）、`verify_database_design.py`（55表/49数据集/12 JSON）均exit0；`py -m pytest -q --tb=short -rs tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py tests/test_storage_help.py --basetemp build/pytest-e6b-status-close-docs --junitxml build/architecture-e6b-status-20261020/close-docs.xml` exit0，35 passed/39.93秒。结案只新增事实证据和状态，不修改产品实现、不另造发布包；补录本段后再作最后review/check。
