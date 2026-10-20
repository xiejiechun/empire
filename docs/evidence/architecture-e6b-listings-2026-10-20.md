# E6b-listings 上市与发行资料实施记录

状态：**开发验证通过**；尚未发布或桌面验收，不进入E6b-status。前批E6a结案main及远程精确为 `9d8ace3615b0fe81fc716a8beb327cf36ae388a9`，工作区干净。安装仍为实现4550a9e、release 7d92659ce1604c3a918e4317f4f7caa6；本批前检实际核实包EXE、原config/偏好、冻结工具以及13348实际server_uuid/datadir、仅四系统库和无其他客户会话，exit0。10:13正常Alt+F4，观察到保存进度、结束归档和关闭连接；随后fresh窗口枚举无Empire。关闭前45任务、活动0、pending0、既有失败5。没有启动子代理。

## 范围与适用验收登记

按手册允许，E6b-listings、E6b-status、E6b-aliases分三批独立发布。此批仅将 `contracts/listings`、`plugins/collectors/ths_listings`、`plugins/datasets/listings`、`plugins/data/listings`、`plugins/ui/listings` 迁至 `features/listings` 的 contract/collector/dataset/query/ui，增加定位README及bundle。原7400/7500/7600插件、3200任务、2300数据集槽位和全部稳定身份保持。同步现行调用方、动态测试patch、显式维护入口、规则、结构/覆盖及设计卡；旧五文件退役，无转发层或双注册。状态/映射的旧实现和remaining其他贡献保留到各自批次。

请求前适用性：正式业务只改归属及导入，不改来源解析、参数、业务字段、完整性、生命周期、恢复及UI行为。本批仍使用固定seed20261020的当前池随机30加既有市场/日期及失败反例做实际链路核对；精确暂无和缺上市日按既有来源状态处理，准备失败不改写为通过。任何实质修复须重新判断完整验收范围，不换样掩盖失败。

适用项为C1～C4身份/顺序/退役，R1～R4来源/集合/修订/冷热摘要/恢复/取消/独立归档，E6b-listings容量新测，T3冻结18项，M正文/覆盖/最后review，A4唯一发布及U1～U3同包配置/真实连接/查询/可见桌面/启停草稿窄窗/正常关开。A1～A3保护实现未改，额外破坏性现场演练不适用；不重复生产DDL、不重启数据库/共享Redis、不清未解决错误。

## 实际开发证据

本地根 `build/architecture-e6b-listings-20261020/`，所有命令使用 `.venv/Scripts/python.exe`。`prepare_migration.py` 从实际前像生成26项精确manifest，经审阅bundle与范围后 `apply_migration.py` 校验全部前像和候选hash再应用。没有整树套用旧E草稿。

| 验收 | 实际命令及证据 | 结果与限制 |
| --- | --- | --- |
| 业务/装配 | `py -m pytest tests/test_ths_listings.py tests/test_all_collector_prefetch.py tests/test_feature_bundles.py tests/test_assembly_order.py --basetemp build/pytest-e6b-listings-unit -q` | exit0，122 passed/1.61秒 |
| 工具安全 | `py -m pytest tests/test_listing_verification.py tests/test_source_verification.py --basetemp build/pytest-e6b-listings-safety -q`；历史固定范围补充后同命令basetemp改safety-2 | 均exit0，104 passed/1 opt-in skipped；实际SQL另运行，不计跳过为通过 |
| 实际SQL及恢复 | 显式 `EMPIRE_INTEGRATION=1`、`EMPIRE_TEST_MYSQL_SETTINGS=build/architecture-evolution-20261019/mysql-settings.json`，运行 `py -m pytest tests/test_listing_verification.py tests/integration/test_listing_archive.py tests/integration/test_prefetch_pipeline.py --basetemp build/pytest-e6b-listings-integration -q --junitxml=build/architecture-e6b-listings-20261020/integration.xml` | exit0，31 passed/117.42秒；含共享私有UUID/owner/SQL守卫、来源合成有效/缺日/暂无三状态到入队/归档/正式查询/准备及清理，非真实来源 |
| 静态/类型 | `py -m ruff check src tests scripts --fix --output-format concise`，随后check；`py -m mypy` | exit0，导入排序修复13处；严格公共边界8文件通过，不称全部旧业务严格类型通过 |
| 架构 | `py scripts/architecture_contract.py check --output build/architecture-e6b-listings-20261020/architecture.json` | exit0，390模块/1428导入，4既有/0新增/43退役债务 |
| 精确装配 | `py scripts/assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json` | exit0，身份/语义/顺序与映射实现精确对应；首次误写不存在的architecture前缀baseline，exit1，纠正路径后通过，不计初次为通过 |

旧verify_listings使用生产写入和最多20证券，旧measure_listings仅凭host/port、无owner/逐连接守卫且在清理前写报告；均未执行。现已复用source_verification/PrivateStorage，取消等待在途SQL工作者退出，恢复按原ownership核实。容量仅额外精确批准本表ANALYZE及四条原查询EXPLAIN，先核实际连接身份，未放宽公共守卫。合成15000行原样本/状态分布/100ms等原阈值保持，新增逐行集合内容核对。容量完整新测尚待运行，旧报告绑定失效不能刷新hash冒充通过。

## 实际来源检查点

`py scripts/verify_listings.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --seed 20261020 --proxy-only --output build/architecture-e6b-listings-20261020/live-1.json`，exit1。原因：301139.SZ已退出现行股票池，不满足共享默认固定样本必须来自池的前置；没有请求来源或创建写资源，六项清理true。只读核实唯一池外固定证券为301139.SZ，stock_listing无该行；未补造业务资料。

补充本领域prepare_scope：随机池/seed/随机30原样保留，301139以已文档化“元道退”历史反例身份额外加入私有请求范围（不计随机，不更改生产stock）；若再次进入池则用真实池记录。报告明确historical_fixed及in_current_pool，并有专项证明不会替换池或随机名单。第二轮同命令仅output改 `live-2.json`，实际结果待完成后追加。

本批未解决既有H3空名债券、E4严格来源失败、资本历史准备限制及停复牌精确错误；不清这些错误、不将组织迁移等价当成来源质量修复。完成后须重开正式桌面；当前不得宣称本批或整个优化完成。

## 最终输入开发验证

| 验收ID | 实际命令/证据 | 结果、范围和限制 |
| --- | --- | --- |
| C3/C4 | `py build/architecture-e6b-listings-20261020/check_equivalence.py`；[五模块正文等价](architecture-e6b-listings-equivalence-2026-10-20.json) | exit0；仅忽略导入AST，全部其余正文精确相等、五旧路径不存在；不能替代真实行为 |
| R1～R4/U开发 | `py -m pytest tests/test_ths_listings.py tests/test_listing_verification.py tests/test_source_verification.py tests/test_archive_queue.py tests/test_fingerprint_versions.py tests/test_ingest_reservations.py tests/test_unit_prefetch.py tests/test_prefetch_budget.py tests/test_all_collector_prefetch.py tests/test_collection_control.py tests/test_manager.py tests/test_feature_bundles.py tests/test_dataset_contributions.py tests/test_assembly_contract.py tests/test_assembly_order.py tests/test_assembly_source_gate.py tests/test_architecture_contract.py tests/test_shared_boundary_injection.py tests/test_ui_architecture.py tests/test_preview_redesign.py tests/test_preview_polish.py tests/test_preview_candidate_activation.py --basetemp build/pytest-e6b-listings-final --junitxml build/architecture-e6b-listings-20261020/public-domain.xml -q` | exit0，489 passed/1 opt-in skipped/26.41秒；真实私有SQL正向此前已单独执行；不把离屏UI当桌面 |
| 真实来源R2 | 上述实采命令output改`live-2.json`，内置帮助最后正文修改后再次同名单完整执行output=`live-3-final.json`；[最终有界报告](architecture-e6b-listings-source-2026-10-20.json) | 两轮均exit0，池5579、随机30+固定11共41，41代理/direct及fallback0，来源/入队/SQL/正式列表、详情及补缺规划逐项集合内容一致、pending0，六清理true/残留false。最终输入摘要以机器报告为准。001381仍incomplete、301139仍unavailable，准备fields/keys/coverage/quality/freshness fail如实保留，不冒充资料完整或生产全池采完 |
| E6b-listings容量 | `py scripts/measure_listings.py --test-mysql-settings build/architecture-evolution-20261019/mysql-settings.json --output build/architecture-e6b-listings-20261020/capacity-1.json`；[新原报告](architecture-e6b-listings-capacity-2026-10-20.json) | exit0，原15000行/15000状态及分布；列表/详情/范围P95 50.264/49.058/47.830ms，覆盖192.484ms，导入23.154秒，完整审计1.347秒，分配126746624字节，状态3647250字节；重复write0、修订write1；原阈值全过，六清理true/残留false。新绑定与DDL已核，不刷新旧报告hash |
| T3 | `py scripts/architecture_benchmark.py measure --test-settings build/architecture-evolution-20261019/mysql-settings.json --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output build/architecture-e6b-listings-20261020/performance-1.json`；[原报告](architecture-e6b-listings-performance-2026-10-20.json) | exit0，原九指标median/p95共18项通过，测量无同期SQL/来源/测试/构建；原harness/协议/基线/阈值不改；不代表来源吞吐或实际桌面性能 |

最后文档审阅首轮exit1：开盘啦七任务共用listings_source的导入路径改变，及MySQL stock_listing归档/查询路径改变，但相应正文未变。已逐项复核：开盘啦仅改公开LISTING_LOOKAHEAD_DAYS导入，同值31/来源行为和既有使用限制均未变；stock_listing未改DDL/字段/身份/索引/清理/恢复，仅代码归属变化。后续以八项明确unchanged理由登记，不改无关文章；最终review/check结果待实际执行。首次verify_documentation因该过期审阅exit1，verify_database_design已exit0，55表/49数据集/12 JSON。


最终文档review/check、verify_documentation和verify_database_design均exit0，236文档/1608链接、55表/49数据集/12 JSON；八项unchanged逐项理由已登记。文档/规则四文件回归命令为 `py -m pytest tests/test_documentation_contracts.py tests/test_documentation_sources.py tests/test_documentation_review.py tests/test_collection_rules.py --basetemp build/pytest-e6b-listings-docs --junitxml build/architecture-e6b-listings-20261020/docs.xml -q`，exit0，41 passed/26.38秒。最终ruff、严格mypy八边界及diff --check exit0。

`py build/architecture-e6b-listings-20261020/pre_release.py` exit0：最终实采source_digest与当前精确一致、容量全部绑定未变、原两config及插件偏好hash保持；只读保存全部48行app_setting payload及updated_at供同包桌面后核对。原冻结性能工具/协议/基线不变，T3比较无incomparable。开发适用出口通过，后续须实现提交、唯一正式发布、同包U1～U3及正常关开；此检查点不得称已验收。
