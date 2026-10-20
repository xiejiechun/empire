# E6b-aliases 证券代码映射实施记录

当前状态：**本批组织迁移范围已验收，结案提交待推送核实**。实现`b96abe26514b0912569b6559b09c3eefe0a684c4`，release `e50fe39d6083405ab7abaf86d90a2561` committed/passed，3793 passed/5 opt-in skipped；同包正式查询、原配置/偏好与48保存设置、真实桌面及正常关开通过。结案推送精确核实后进入E6c，整个优化未完成。2026-10-20从已验收并推送的E6b-status结案`290a6ae458f2f878772a9107d55f5732aea740b8`接续，开工工作区干净、远程精确匹配；前批release `dad5a84751e44fe1a6f35ef4e577c7b0`已核实。

## 请求前范围与不变量

旧`plugins/collectors/bse_code_mapping_source.py`拆至`features/security_aliases/source.py`及纯`contract.py`（URL/LIMIT/validate），旧`plugins/datasets/security_aliases.py`迁至该包`dataset.py`。旧文件删除，同步维护脚本、测试、coverage和架构声明；remaining只移出本批dataset槽位2000及维护发布者，builtin新增一个业务工厂。无转发、双登记或新增后台采集。

保留JOB bse-code-mapping-v1、PROJECT bse-code-mapping、dataset bse.code_mapping.complete、schema1、namespace bse_code_mapping_v1、原表/主键/唯一索引/状态和版本契约。官方整表解析、历史关系保留、冲突整事务拒绝、元数据修订、零DML及旧响应保护不变；显式`scripts/import_bse_code_mapping.py --apply`仍持正常单实例锁并走唯一共享下载/入队/归档。没有DDL变化，不执行生产导入或造容量数据。

适用验收：C1/C2精确装配和顺序，C3/C4退役/归属，R1～R4来源/规范/冷热摘要/事务及确认失败重放，私有SQL守卫、取消和独立清理，1000行原容量协议及T3，M文档，A完整正式发布及A4同包真实连接/查询/配置和桌面。U1/U2业务页面/任务草稿不适用：本业务只有显式维护发布者；公共桌面启动、运行状态、帮助及正常关开仍需实际验收。

真实来源单位是一次完整官方换码表，非按股票请求；不以当前股票池过滤历史关系。随机30股不适用，不宣称满足30股门槛；额外保留836149→920149.BJ固定例。真实代理整表验证与1000行合成容量分开记录。无本批错误ID修复，不清现有错误；前批H3/E4来源失败、资本历史准备及生产历史freshness限制保留。

## 开工资源核实

本机`build/architecture-e6b-aliases-20261020/preflight-resource.json`由只读核查实际生成：生产3307 UUID `77f9ba30-b666-11f1-81c5-380525361d4e`，自有13348 UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`及本轮mysql-data目录匹配；测试实例仅四系统库、无其他客户会话。共享队列当时0；config及原偏好hash保留，冻结工具未变化。进程核查未发现其他测试/实采/发布/维护。桌面关闭前实际观察0活动任务/0待归档，Alt+F4后显示正常保存与关闭连接提示；退出完成另核实。

实际应用器与精确前像保存在ignored本批目录；从当前正式两文件重建，未套E全树草稿。初次静态architecture exit0（0新债务，退役45项）、assembly精确身份/六类顺序check exit0；其余验证待执行。

## 实际开发证据与命令

下列`py`均为项目`.venv/Scripts/python.exe`，输出目录`build/architecture-e6b-aliases-20261020`；集成环境显式`EMPIRE_INTEGRATION=1`和`EMPIRE_TEST_MYSQL_SETTINGS=<已核实13348设置绝对路径>`，未改生产配置。来源、容量、测试及T3串行；T3测量期间无其他扫描/测试/构建。

| 验收ID/范围 | 实际命令、退出码及证据 | 结果与限制 |
| --- | --- | --- |
| C1/C2 | `py scripts/assembly_contract.py snapshot --output <out>/assembly.json`及`check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json`均exit0 | 精确身份、语义与六类顺序保持；维护贡献唯一 |
| C3/C4 | `py scripts/architecture_contract.py check --output <out>/architecture-final.json` exit0；`py <out>/check_equivalence.py` exit0，[等价报告](architecture-e6b-aliases-equivalence-2026-10-20.json)、[前像](architecture-e6b-aliases-preimage-2026-10-20.json) | 395模块/1436导入/0新增债务/45退役债务；3解析/校验定义、6数据集定义及维护run完整AST相同，仅职责导入变化。退役两旧文件。AST不代替实际链路 |
| 静态/类型 | `py -m ruff check <本批包、三脚本及三测试>` exit0；`py -m mypy` exit0 | 8个已登记strict公共文件无错误；未声称全部业务已有strict类型 |
| R1～R3/私有资源 | `py -m pytest tests/test_bse_code_mapping.py tests/test_existing_capacity_tools.py tests/test_source_verification.py tests/integration/test_security_alias_archive.py --basetemp build/pytest-e6b-aliases-final-sql -q --junitxml <out>/final-sql.xml` exit0 | **114 passed / 9.07秒，无skip**；真实UUID私有SQL→Redis→统一归档→SQL，冷/热摘要/修订/旧响应/确认及SQL失败重放。精确放行两句SQL前核实际实例/库，其他EXPLAIN/ANALYZE/跨库/多语句拒绝；取消还原网络策略；来源/SQL等数异内容拒绝。共享取消/独立清理反例及真实正向清理通过 |
| R4/公共路径 | `py -m pytest tests/test_bse_code_mapping.py tests/test_existing_capacity_tools.py tests/test_archive_queue.py tests/test_fingerprint_versions.py tests/test_ingest_reservations.py tests/test_unit_prefetch.py tests/test_prefetch_budget.py tests/test_all_collector_prefetch.py tests/test_collection_control.py tests/test_manager.py tests/test_feature_bundles.py tests/test_dataset_contributions.py tests/test_assembly_contract.py tests/test_assembly_order.py tests/test_assembly_source_gate.py tests/test_architecture_contract.py tests/test_ui_architecture.py tests/test_ui_architecture_counterexamples.py --basetemp build/pytest-e6b-aliases-public -q --junitxml <out>/public.xml` exit0 | **329 passed / 1 opt-in skipped / 26.56秒**。该opt-in已在114隔离轮实际执行；不能把跳过计通过。本业务单完整响应，无分页/后页预取；公共入队隔离竞态/取消/成功清队保持 |
| R2真实来源 | `py scripts/verify_bse_code_mapping.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --proxy-only --output <out>/live-3-final.json` exit0，[原报告](architecture-e6b-aliases-source-2026-10-20.json) | 1次共享代理请求、248项/459945字节完整官方表；来源→规范→Redis→统一归档→有序正式SQL逐字段集合完全一致，固定836149→920149.BJ保留。直连/回退0、pending0、六清理true、无SQL/Redis残留；30股N/A，未变更生产关系 |
| 容量 | `py scripts/measure_bse_capacity.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --output <out>/capacity-3-final.json` exit0，[原报告](architecture-e6b-aliases-capacity-2026-10-20.json) | 固定1000行精确集合/内容，checkpoint→publish_page→archive.flush，**41.6096ms/4.5560ms/131072字节**，原预算2000ms/100ms/1048576字节；ux_alias_security实际命中，pending0，六清理true，无残留。实际环境/DDL/绑定保留；不请求来源，不证明生产容量吞吐 |
| T3 | `py scripts/architecture_benchmark.py measure --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output <out>/performance-1.json` exit0，[原报告](architecture-e6b-aliases-performance-2026-10-20.json) | 冻结协议9指标median/p95共**18/18**、无不可比项、cleanup true；工具、历史基线、阈值未改。离屏代表负载不冒充真实桌面 |
| M文档/存储 | `py scripts/documentation_contract.py review --note <本批具体审阅> --unchanged-reason <其他业务未变理由>`、`check`、`verify_documentation.py`、`verify_database_design.py`均exit0；`py -m pytest tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py tests/test_storage_help.py --basetemp build/pytest-e6b-aliases-docs -q --junitxml <out>/docs.xml` exit0 | 242文档/1636链接，55表/49数据集/12 JSON；35文档回归/24.72秒。来源手册、内置表参考、README和coverage同步；所有active measured绑定实测核实有效，仅本批BSE卡改引新报告。最终事实更新后再review |

首轮安全测试发现新实采工具main括号语法错误（107 passed/3 failed/1 skipped，exit1），未运行来源、未取得通过；已修复并保留`safety.xml`。修复后110 passed/1 opt-in skipped，最终114隔离轮全部实际通过。容量前两通过轮仍保留，最后补全容量取舍字段后第三轮真实重测，未刷新旧报告数字/hash。原集成容量测试改写本测试tmp_path，避免以后覆盖旧ignored容量文件；测量协议、样本及阈值不变。

`py <out>/pre_release.py` exit0：最终来源摘要与实际树一致、容量所有bindings不变、两config及原偏好hash保持；只读保存全部48行app_setting（含payload与updated_at）供同包核验，私密原值仅留ignored目录。正式发布前桌面已正常退出，未强杀或删除锁。无本批业务错误ID清理。

## A/M/U 正式发布与结案证据

| 验收ID/范围 | 实际命令、退出码与证据 | 结果及限制 |
| --- | --- | --- |
| A1～A4 完整正式发布 | `.\verify-release.ps1` 自然退出0；release `e50fe39d6083405ab7abaf86d90a2561`，本机`release-console.log`、publication及24步日志保留；`py <out>/audit_release.py` exit0，[审计](architecture-e6b-aliases-release-audit-2026-10-20.json) | journal committed/passed，3793 passed/5 skipped/20 warnings/2396.62秒；5个state-unit opt-in跳过不计通过。1620输入精确一致、54保留输出核实、24步骤完成；HEAD和受保护输入全程冻结。可选QML插件构建警告原样保留 |
| A4/U3 同包配置/连接/正式查询 | `py <out>/check_published_runtime.py --run e50fe39d6083405ab7abaf86d90a2561 --report <out>/post-release.json`及关闭后`--report <out>/post-release-closed.json`均exit0，[关闭后报告](architecture-e6b-aliases-post-release-closed-2026-10-20.json) | 正式EXE在C:/Windows cwd的doctor真实连接通过；生产248项及固定例、两个索引查询集合内容一致，恰与本轮官方整表相同；只读，不执行生产import，不作生产新鲜度声明 |
| U1/U2/U3 真实桌面 | computer-use/sky实际操作，详见[真实桌面](architecture-e6b-aliases-desktop-2026-10-20.md)和[观察索引](architecture-e6b-aliases-desktop-observations-2026-10-20.json) | 真实运行状态构建标识、帮助搜索/正文/滚动、正常退出及重开、本地连接和45任务/0活动/既有失败4/pending0。领域页面启停/草稿N/A，本业务没有这些贡献；不冒充桌面全部业务验收 |
| U3 设置保留 | `py <out>/close_desktop_settings.py` exit0，[保存设置](architecture-e6b-aliases-settings-2026-10-20.json)；重开后Get-FileHash再次核实 | 两config SHA256均`5c1e32fdf651b948c387106d2a006ba390b7cb1001827fc537262deae832f92f`，偏好`8cbc58900b35bf4c8b2f9fff47ed95f67f6e20782734f38a0819ff3c7cadd63e`原字节不变，无需恢复；48行payload/updated_at摘要`9e59d702765610a9f91bfdfcc19bcfc104590d239bd87be6dfa99a95c511c1ac`相同 |
| 资源与冻结边界 | `py <out>/final_resource.py` exit0，[最终资源](architecture-e6b-aliases-final-resources-2026-10-20.json) | 私有13348实际UUID/datadir，四系统库、无其他客户，生产与测试隔离；冻结工具/原阈值未变，pending0，无锁/共享Redis/生产业务清理 |

正式EXE SHA256 `ed8ed8d58ae3a8b3bf712ae8e953acdcf5454ed0e827b0f36d5a4c537ba68be1`，安装树`1f6a8abade47f3bd0e40f77eeb129729182d6a31543d6d3eaef30db66b817c9b`，source `428c85bbd53d5ad3bdb349efa3db0cbbec4ef38149b46a49ad9679666d2a7a8f`。机器报告原desktop pending字段未改，用独立实际记录补足。`py <out>/finalize_evidence.py` exit0复制原机器收据并索引26份真实文件，[证据索引](architecture-e6b-aliases-evidence-index-2026-10-20.json)不包含私密设置/owner或成功HTML全文。

结案只更新验收事实，不更改已发布运行时代码或正文。最终`documentation_contract.py review`与`check`、`verify_documentation.py`（243文档/1655链接）、`verify_database_design.py`（55表/49数据集/12JSON）实际均exit0；同前述四个文档测试、`--basetemp build/pytest-e6b-aliases-closure-docs --junitxml <out>/closure-docs.xml`实际exit0，35 passed/25.42秒。结案提交/push与远程精确核实完成后才能实施E6c；H3/E4、资本历史和生产历史freshness失败不冲销，随机30股N/A不计满足股票门槛。
