# 架构治理逐阶段验收手册

本文是后续 AI 的执行与验收手册；预期标准和历史事实分别标明，不能将标准表当成成功报告。实施步骤见 [C/D/F 实施](cdf-implementation.md)、[E 分批实施](e-implementation.md)；目标与验收 ID 继续以[总方案](../architecture-evolution-plan.md)为准。本手册不替代[开发流程](../development-workflow.md)、[采集指南](../collector-development-guide.md)、[数据库设计规范](../database-design-standard.md)和[发布门禁](../release-gate-review.md)。

编写快照为 2026-10-19，C 第二轮正式门禁及发布后的实际核查已完成，详见[状态账本](status.md)与所引证据。当前交付范围是文档，不合入 D～F。后续执行者先核实实际 Git、发布 journal 和操作所有者，再更新状态；不要把本文中的路径、命令或预期结果当作已经实现或执行的保障。

## 1. 当前事实与交接边界

| 阶段 | 已有事实 | 仍不能据此声称 |
| --- | --- | --- |
| A/B | 正式发布 `7feb3f35333d4404aae8684dd2f6ddf6`，提交 `e4dafe72b676075ccdeb2add54f0731f9cb1691f`；3403 passed、5 skipped；配置/偏好保留、异工作目录真实连接、正式查询、可见桌面和正常退出已验证。见 [A/B 记录](../evidence/architecture-ab-2026-10-19.md)及本地 `build/architecture-evolution-20261019/post-release-ab-accepted.json` | 不能沿用其包身份证明 C/D/E/F；5 skipped 不算通过；当时仍有一条日常任务待归档，未手工删除 |
| C 开发/实际范围 | 新闻收拢、任务契约和装配入口已实现；新闻有限实采为共享代理1请求、1页50条，集合/内容与正式查询一致、待归档0；冻结T3九指标median/p95共18项通过；具体证据见 [C 记录](../evidence/architecture-c-2026-10-19.md) | 不表示全部新闻历史完整；新包实际桌面证据单列，不由开发测试推断 |
| C 正式发布 | 首轮 `4a1e7b817c264d20b61f4db85352c85d` 因测试旧装配入口失败，未打包/切换；修复后 `8fbd5bd7a9cf460a9b82022b7e643f1d` 已成功，绑定提交 `81e147f35ba6af89b8b08219fe533130c875313c`，3494 passed、5 opt-in skipped、20 warnings、2254.92秒；完整源摘要 `325b3eb337f2907790f7fb9d37cc83300c10d9f53fd815dc24bea2c3054e01e7` | 发布后已真实核实安装身份、配置/偏好、异cwd连接、查询、可见窗口及6项中文输出；详见状态账本，不表示D–F通过 |
| D | 持有人迁移、文档、安全实采验证器、SQL正向smoke、容量安全修补和类型等有 build 草案 | 未正式集成，未运行这些候选的 pytest/mypy/SQL/来源或发布；AST、hash或文本等价不是运行通过 |
| E | 分阶段迁移、共享边界、SQL表权威及文档/容量矩阵有 build 草案 | 不能整体复制后宣称逐批完成；分红完整容量方案仍有明确缺口，部分容量入口尚未审查/验证 |
| F | 影响报告、公共类型、共享依赖门禁、元数据、测试建表成本及定位演练有 build 草案 | 选择性测试不替代全量门禁；成本优化没有实测收益前不采纳；草案检查不等于业务和真实桌面验收 |

C实际发布后报告见[已提交证据](../evidence/architecture-c-post-release-2026-10-19.json)：14:36检查通过、待归档0；可见窗口版本/股票/新闻/连接正常，Alt+F4后fresh窗口列表为空。它只覆盖记载范围；后续批次必须取得自己的真实证据，禁止复制其passed。

## 2. 每轮开始前的核实清单

### 2.1 工作区、输入和执行权

1. 阅读根 AGENTS 与本批业务 README/权威说明。确定本批只包含一个可回退的业务迁移或明确公共改造，登记目标、非目标、受影响能力和测试。
2. 读取 Git 状态、提交、工作树和远程，辨认其他任务已有变更。不要清理不认识的文件、覆盖已有草案，或把它们混入自己的提交。
3. 核实是否存在发布、容量/T3、数据库维护、来源验收或桌面会话。独立 worktree 不隔离数据库、Redis、dist、发布锁或桌面。共享环境操作串行；有活动发布时只做获准的 build 文本准备，不运行候选导入、lint、测试、扫描、DB或构建。
4. 本交接后续批次禁止修改 `scripts/release_lock.py`、冻结 T3 harness、协议与历史基线来使当前结果通过。发现这些文件需要修复时，记录问题并拆出独立审阅范围，不夹带进业务迁移。
5. 停止实现编辑后才建立当前验收输入身份。后续任何实现、测试、SQL、资源、文档或工具变化都要重新判断失效范围；正式发布按完整输入重新验证。

以下为只读核实示例；从项目根目录执行，记录实际输出，不能把示例当结果：

```powershell
git status --short
git branch --show-current
git rev-parse HEAD
git worktree list
git remote -v
git diff --stat
git diff --check
Get-FileHash -Algorithm SHA256 -LiteralPath scripts/release_lock.py
Get-FileHash -Algorithm SHA256 -LiteralPath scripts/architecture_benchmark.py
Get-FileHash -Algorithm SHA256 -LiteralPath scripts/architecture_benchmark_data.py
Get-FileHash -Algorithm SHA256 -LiteralPath docs/evidence/architecture-performance-protocol-2026-10-19.json
```

不输出 `config.toml` 或连接 JSON 正文。真实配置不纳入 Git、公共包或公开报告；只保存脱敏身份及必要摘要。本地含配置的 dist/previous/staging 也不能直接公开分发。

### 2.2 验证工具必须先存在且符合当前契约

每个命令先确认脚本/测试路径存在，读 argparse、输入要求及副作用；解冻后才可执行 `--help`。旧同名脚本存在不代表已替换为安全版本，尤其正式 `verify_ths_holders.py`/`verify_ths_statements.py` 与 D 草案同名。应核对集成 manifest、实际 diff、导入路径与清理回归。

| 工具类别 | 本快照状态 | 执行前必须补足 |
| --- | --- | --- |
| verify-release/build、architecture_contract、assembly_contract、documentation_contract、architecture_benchmark | 正式路径已有 | 核实当前版本、输入身份和共享环境；仍不能绕过各自前置条件 |
| D `source_test_storage.py`、`source_verification.py`、安全持有人/财报命令 | `build/holder-verifier-draft-20261019` 草案 | 正式集成、guard/生命周期反例、实际初始化SQL正向smoke、适用业务专项；不要混入旧独立财报 helper |
| `smoke_source_storage_sql.py` | `build/d-sql-positive-smoke-20261019` 草案 | 与已集成 D helper/领域路径一致；实际13348运行并核对结果，不能仅用静态清单 |
| `capacity_session.py` 与三测量器修补 | `build/capacity-safety-draft` 草案 | 按 D/E manifest 精确集成；原协议/阈值不变；故障清理和实际测量通过 |
| `measure_bse_capacity.py` / `measure_existing_capacity.py` | `build/readonly-capacity-draft` 草案 | helper契约/额外SQL精确白名单复核、反例和真实隔离执行；分红只读诊断始终不能冒充完整容量 |
| F change_impact、schema_fixture/ddl、共享门禁/类型 | 对应 `build/f-*` 草案 | 实现、专项、负例、真实类型检查/测量；选择报告和测试优化不能成为新的绕过入口 |

脚本缺失、CLI不符、导入失败、缺配置或依赖服务不可用时记录 `not_run/blocked/failed`，完成必要实现或准备后再执行。不得通过手工创建一个 `passed:true` JSON、改证据绑定hash、扩大skip、重建历史基线或设置成功退出码来解除门禁。

## 3. 统一执行顺序与结果状态

每阶段顺序为：范围/反例 → 最终实现与调用方/旧路径退役 → 适用专项 → 隔离端到端/恢复 → 真实范围实采（适用时） → 受影响容量 → 冻结T3 → 文档语义审阅/契约 → 完整发布 → 同包真实核查 → 提交/远程身份和交付记录。没有依赖关系的静态工作可并行，数据库、来源、T3、发布和桌面操作按共享环境串行。

结果状态统一采用以下语义，不能混用：

| 状态 | 含义 | 能否满足适用退出条件 |
| --- | --- | --- |
| `not_run` | 尚未执行，含只有脚本/草案/AST检查 | 否 |
| `running` | 有真实进程和本轮ID，尚无最终结果 | 否 |
| `failed` | 执行失败、断言失败、超预算、清理失败或报告不完整 | 否 |
| `blocked` | 明确外部条件或前置项缺失，写出阻塞及下一步 | 否 |
| `partial` | 已取得部分证据，必要部分仍未知或失败 | 否；只可交付已经证明的范围 |
| `not_applicable` | 按业务/改动性质不适用，附理由及替代证据 | 仅对应该不适用项；不是PASS |
| `passed` | 真实执行、输入正确、全部适用断言及清理通过，证据审核通过 | 是，仅限记录范围 |

pytest 的 `skipped/xfail` 分别保留原始原因；不把计数合并进 passed。隔离 state-unit 默认 opt-in 跳过的5项只证明未运行：若本批改动正涉及 state-unit/JSON状态恢复，必须按该文件的明确启用方式补跑，不能沿用 A/B 的不适用解释。未知动态依赖、公共协议变化或无法完整确定影响范围时扩大回归。

## 4. A～F 阶段退出矩阵

### 4.1 A：发布身份与保护（A1～A4）

| ID | 具体检查/路径 | 必须观察的反例与成功事实 | 证据和失败处理 |
| --- | --- | --- | --- |
| A1 | `tests/test_release_pipeline.py`、`test_release_entrypoints.py`、`test_release_steps.py`、`test_release_output.py` | 第二发布拒绝、子进程仍持所有权、失败/取消只回收自己资源；不删除锁、不强杀未知进程 | JUnit、实际子进程输出及owner；失败保留旧包，禁止跳锁重试 |
| A2 | 上述管线测试及 `tests/test_release_gate.py` | 测试前后/打包/切换前内容或stat变化、改后恢复字节、证据改动均拒绝 | 完整输入、Git、各阶段输出摘要与失败日志；不能把旧证据重新hash作为新验证 |
| A3 | 发布中断/被占用/配置及journal反例 | 构建或切换失败保留可运行旧包和配置；自己暂存目录身份可核实 | 原/候选文件树与配置摘要、journal；正常恢复入口 `verify-release.ps1 -Recover`，不手工猜目录删除 |
| A4 | `tests/test_package_smoke_declarations.py`、`tests/test_desktop_runtime.py`，真实完整发布 | writer→reader当前清单契约、全部真实声明构造、无服务smoke；发布后可见窗口与正式查询另验 | commit/source/evidence/exe/tree/config链齐全；无窗口或Invalid manifest一律不能完成A4/U3 |

A/B 已有成功证据，后续无需无缘无故重复破坏性故障演练；若更改发布相关代码，重跑相应反例。每批正式发布仍使用同一唯一入口，不复用旧包验收。

### 4.2 B：诊断与定位（总方案 D1～D3）

“D1～D3”是总方案诊断验收编号，不是股东 D 批次。

| ID | 实施入口/测试 | 通过标准 |
| --- | --- | --- |
| D1 | `python -m empire doctor --project <正式任务ID> --output <新build文件>`；`tests/test_project_diagnostics.py` | 错误精确ID、阶段、next_due、断点、队列、隔离、范围和正式查询分别带时间/状态；四类现场/隔离样本清楚分开 |
| D2 | `tests/integration/test_project_diagnostic_mysql.py` 及诊断专项 | 默认SQL≤10、Redis≤20、单I/O≤5秒、整体≤30秒、报告≤1MiB；错误摘要≤50，确切ID正文≤64KiB；真实建连读取预算计入；一侧失败仍保留另一侧 |
| D3 | 诊断前后私有库/Redis内容与版本对比 | 不启动collector/archive，不写业务/断点/摘要时效/错误列表；凭据脱敏、查询线程已回收 |

独立 doctor 无IPC时进程内隔离为unknown是诚实结果，不可改成false。partial退出不能写完全通过。真实共享环境只做允许的有界只读核查，不为制造反例关闭生产数据库/Redis。

### 4.3 C：装配与新闻样板（C1～C4、R1～R4、U1～U3）

| 组 | 测试/命令与核对点 | 退出条件 |
| --- | --- | --- |
| C1/C2 | `tests/test_feature_bundles.py`、`test_assembly_contract.py`、`test_assembly_order.py`、`test_assembly_source_gate.py`、`test_dataset_contributions.py`、`test_manager.py` | 精确插件/能力/任务/dataset/project/namespace/schema/page/preparation身份及六类顺序相同；重复/归属错误/缺依赖/环/维护入口缺失拒绝；纯声明构造无文件I/O、联网或QWidget实例 |
| C3/C4 | architecture_contract、assembly_contract；搜索退役旧新闻模块/任务默认值入口 | 无新增债务；映射明确且目标/测试存在；没有双注册、转发模块或执行入口遗留；历史evidence保留原貌 |
| R1 重复/修订/重放 | `tests/test_sina_news.py`、`test_news_query.py`、`test_news_ui.py`；`tests/integration/test_news_archive.py` | 首次/fresh/续采边界、修订及迟到旧版、摘要冷热、相同内容免DML、可信摘要命中免MySQL访问、SQL提交后确认失败安全重放及成功清队；正式列表/正文一致 |
| R2 集合/完整性 | `tests/test_sina_news.py`、`test_incomplete_response.py`、`test_http_response_safety.py`、`test_ingest_reservations.py`及本批来源专项 | 按来源适用项覆盖缺页、同数异集、必需关联缺失、同键跨页重排、空值与超限；核对集合与内容，错误不推进完成断点；不适用项说明原因 |
| R3 调度/取消/清理 | `tests/test_collection_control.py`、`test_unit_prefetch.py`、`test_prefetch_budget.py`、`test_manager.py`及本批生命周期专项 | 手动与到期并发、暂停恢复、取消预取及插件失败；同任务不重叠、结束后计等待间隔、全部请求/额度回收，旧所有者未清理完不能创建第二所有者 |
| R4 入队/独立归档 | `tests/integration/test_archive_fairness.py`、`test_live_pipeline.py`、`test_prefetch_pipeline.py`及相关archive/ingest专项 | 后批下载与前批归档重叠；按序入队后继续下载，仅整轮末等待归档；即刻唤醒与60秒恢复保留，失败消息留队、成功即清队，无第二队列/下载器/调度器 |
| 实际来源 | 本轮限定新闻窗口，正式共享下载/代理及存储/查询路径 | 非股票粒度，30股票不适用；仍记录页面/ID集合、内容摘要、proxy/direct/fallback计数、完成状态和本轮pending=0 |
| U1～U3 发布/桌面 | 本轮完整门禁、第10.3节同包U项 | C第二轮门禁已通过，仍须核对其实际产物；UTF-8真实EXE输出、原配置/偏好、新闻列表/正文和正常退出都要实际验证 |

已有 C 业务实采/T3证据若对应业务实现未变，可经明确输入差异审核复用其适用范围；最终全量发布必须使用修复后新提交。不要把“只改测试”的解释扩展成跨任意源码的证据复用。

### 4.4 D：持有人复杂样板（H1～H3，继承C/R/U/T/M）

| 验收 | 必跑路径与实际方法 | 退出条件 |
| --- | --- | --- |
| H1 身份/共享HTML | 装配快照；`tests/test_holder_combined.py`、`test_ths_holders.py`；THS资本来源/传输专项 | 仍一个任务一次必要HTML三栏、三独立查询/页面；response_group不变；资本继续共用一处HTML辅助，不导入持有人私有实现 |
| H2 业务反例 | `test_holder_quality.py`、`test_holder_identity_gaps.py`、`test_holder_error_shapes.py`；`tests/integration/test_holder_archive.py`、`test_holder_run_outcome.py`、`test_holder_source_migration.py` | 并列排名、缺口/空栏、窗口变化、同数异集、旧记录补齐、部分失败仍处理后证券、下轮从首缺口恢复；来源缺口不补造、不提前complete |
| D安全工具 | 草案的 `tests/test_source_verification.py`、`tests/test_verify_ths_holders.py`，集成后独立SQL smoke | 非生产实例、UUID归属、跨库/多语句拒绝、SQL实际初始化/require_schema/正式读写可用；清理失败和配置/源漂移不能PASS |
| H3 D实采 | 安全 `verify_ths_holders.py`，第6节 | 随机30+固定反例、实际共享代理、完整正式链路及集合/内容、所有适用样本成功、pending=0；已知gaps不豁免 |
| D容量 | 持有人与THS资本两份新实测，第8节 | 共享HTML路径改动也使资本绑定失效；新安全工具、原样本和阈值、清理完成后出报告 |
| D类型/桌面 | 最终持有人公开契约严格mypy，三页面和任务独立生命周期 | 实际mypy通过而非AST推断；正式包三页/任务/数据与原稳定身份一致 |

### 4.5 E：逐业务推广

每个 E 子批独立出具本手册统一记录，前批没有退出证据不得扩大到下一批。具体文件责任及迁移顺序见 [E 实施](e-implementation.md)。

| 子阶段 | 最少专项/隔离集成覆盖 | 特有退出项 |
| --- | --- | --- |
| E0 SQL权威与公共边界 | `tests/test_business_schema_contract.py`、`tests/test_market_mapping.py`、新共享schema反例、装配/文档存储回归 | 单一SQL归属资源/通用读者；表键集合、固定来源、主键及显式免项互斥完整；不把公开协议移进业务，不启动DDL |
| E1 财报 | `tests/test_ths_statements.py`、`tests/integration/test_financial_archive.py`，安全财报验证器领域/共用测试 | 三表正式query/audit与旧输入等价；chain属于财报公开业务契约；金额/可用日期质量单列；实质变化按30股规则 |
| E2 行业/指数/指数行情 | 对应 `test_industry_archive.py`、`test_index_archive.py`、`test_index_price_archive.py` 及来源/页面专项 | 正式查询与覆盖证明、目录/行情/缺值/旧响应语义不变；索引目录与行情容量新测 |
| E3 股票/日历/停复牌/准备/公共UI | `test_stock_archive.py`、`test_calendar_archive.py`、`test_suspension_archive.py`，确认/preparation和UI生命周期回归 | `contracts/preparation.py`、`contracts/preparation_scope.py` 保持公共唯一权威；Redis可选证据仍可选；共享UI不反向业务；不因容量未失效跳过行为验证 |
| E4 开盘啦 | `test_kaipanla_source.py`、`test_kaipanla_products.py`、`test_kaipanla_intraday.py`、相应UI；`test_kaipanla_products_archive.py`、`test_kaipanla_suspension_scope.py` | 七产品身份、日期范围及正式查询不依赖采集执行器；预览7种样本齐全，新查询容量；旧v1写入容量不得冒充当前v2实测 |
| E5 资本运作/分红 | `test_capital_lifecycle.py`、`test_capital_recovery.py`、`test_capital_preparation.py`、`test_capital_ui.py`；`test_capital_archive.py`、`test_issue_availability_archive.py` | 分红完整容量方案先补齐；只读当前SQL诊断的exit2不得转成完整通过；来源计数/计划期数不能复制旧值 |
| E6a THS资本 | THS资本来源/transport/lifecycle/verification/UI与 `test_ths_capital_archive.py` | 完成最终业务迁移/表权威接入后再次重测资本容量，D容量不能自动覆盖新绑定 |
| E6b 上市/状态/北交所映射 | `test_listing_archive.py`、`test_listing_status_archive.py`、`test_security_alias_archive.py` 及来源/UI专项 | 可再拆独立批；BSE1000行合成完整容量与真实来源完整性分别记录；维护发布者身份/脚本精确对应 |
| E6c～g 名称/ST、解禁、绩效/股东变动、回购、规则 | 对应现有 `tests/integration/test_name_archive.py`、`test_st_archive.py`、`test_tdx_unlocks_archive.py`、`test_tdx_unlock_industries_archive.py`、`test_tdx_performance_archive.py`、`test_tdx_shareholder_changes_archive.py`、`test_repurchase_archive.py`、`test_rule_archive.py`，加各自来源/UI/恢复专项 | 按业务生命周期逐项验证和逐份容量重测；不以一批总测试数代替另一个来源的语义/实采证据 |

表中的集成文件均位于 `tests/integration/`，专项位于 `tests/`。实际变更前用 `rg --files tests` 核实文件；新生成的专项若尚未实现须明确补齐，不能以名称存在于文档替代测试。E最终退出再核对：query/UI/dataset→采集执行器依赖为0、跨业务私有导入为0、共享平台→具体业务违规为0、中央白名单和正式路径唯一，原依赖债务逐条有去向。

### 4.6 F：文档、类型、测试选择与共享热点

| ID/项目 | 执行及负例 | 退出条件 |
| --- | --- | --- |
| M1 定位演练 | 原因已确认只属于业务的页面文案/来源字段，以及新增独立业务三类；记录实际读取/修改文件、定位入口、测试和必要SQL/文档登记 | 前两类不改无关业务/core/基础设施；公共根因修唯一公共路径并扩大回归，不能复制补丁迎合指标；新增业务最多一项中央白名单；演练不能提交伪业务或污染正式SQL |
| M2/M3 文档单源 | 读当前正文权威，确定性生成两次逐字节比较；主题增删/重命名、help链接、页面/任务/表键覆盖反例；现有documentation专项 | 唯一权威正文，阅读器与打包资源都有效；不手工维护新旧两份；无重复文章/失效主题；人工语义审阅与自动门禁都通过 |
| T1 影响报告 | 候选 `scripts/change_impact.py`、`tests/test_change_impact.py`；核对当前贡献、归属和依赖 | 删除/重命名/公共契约/未知动态依赖扩大范围；没有依据不能输出“无需测试”；报告本身不能代替运行结果，更不能跳完整发布 |
| T2 公共类型 | 严格mypy保留现有覆盖并追加真正公共边界；新候选stocks/api、calendar/api/contract、contracts/preparation、contracts/confirmation及已纳入holders/KPL | 实际严格检查通过；Any只限逐项说明的外部载荷边界，禁止ignore_errors/ignore_missing_imports/follow_imports=skip；不靠cast或注释隐藏错误 |
| 共享门禁 | `tests/test_architecture_contract.py` 追加平台→业务公开/私有/再导出/相对/局部/type-only/dynamic字面量反例；owner.kind非法、kernel冒充composition也拒绝 | 最终只保留权威 `shared_to_business`，替换E旧分支避免重复；application真实composition/dataset_registry和diagnostics真实composition例外受审；不抄入debt基线 |
| 元数据职责 | build_info→application/api；help_content→ui_components/parser；help_reader→ui_components/shared_ui；真实职责人工核对 | 不通过把业务虚标platform或composition绕门禁；帮助页面仍业务所有；其他owner/debt/顺序不被旧整份JSON覆盖 |
| 测试成本优化 | 冻结用例集合/断言/skip，分开测收集、建库初始化、执行、清理；候选schema_fixture/ddl/ownership反例 | 每用例独立可变库和Redis、严格归属、必要表/schema/事务/重放语义不减；有真实重复测量收益才采纳。无收益或复杂度高则保留现行实现，记录研究结论 |
| T3 | 第9节冻结协议 | 全18项统计、内容正确性、环境/输入/cleanup满足；测试更快不能替代产品T3 |

## 5. 可执行测试命令模板

以下只能在本批正式集成、共享环境解冻、前置项已核实之后运行。使用本轮唯一目录和报告，避免覆盖失败/历史证据。`$acceptanceRun`、`$testMysqlPath` 必须由执行者设为本轮标识和已核实的私有连接路径，不把占位符直接传命令。

```powershell
$acceptanceRun = 'D-实际日期-唯一标识'
$testMysqlPath = 'D:/project/empire/build/已核实的13348连接.json'
Test-Path -LiteralPath $testMysqlPath
Test-Path -LiteralPath scripts/source_verification.py
Test-Path -LiteralPath scripts/source_test_storage.py
```

静态/装配（预期exit0，但必须读取输出及JSON而非只看最后一行）：

```powershell
.venv/Scripts/python scripts/architecture_contract.py check --output build/acceptance-architecture.json
.venv/Scripts/python scripts/assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json
.venv/Scripts/python scripts/assembly_contract.py snapshot --output build/acceptance-assembly.json
.venv/Scripts/python -m ruff check src tests scripts
.venv/Scripts/python -m mypy
```

实际执行时把两个输出名替换为本轮独立文件。装配baseline/order baseline不得重建；只在受审 `assembly-migrations.json` 声明路径映射，业务语义差异必须解释并按新功能另验。

D定向示例（其他阶段按矩阵换成真实选定用例，不使用宽泛 `-k` 静默漏测）：

```powershell
.venv/Scripts/python -m pytest -q --tb=short -rs tests/test_ths_holders.py tests/test_holder_combined.py tests/test_holder_quality.py tests/test_holder_identity_gaps.py tests/test_holder_error_shapes.py tests/test_holder_ui.py tests/test_source_verification.py tests/test_verify_ths_holders.py --basetemp "build/pytest-$acceptanceRun-unit" --junitxml "build/$acceptanceRun-unit.xml"
$env:EMPIRE_INTEGRATION = '1'
$env:EMPIRE_TEST_MYSQL_SETTINGS = $testMysqlPath
.venv/Scripts/python -m pytest -q --tb=short -rs tests/integration/test_holder_archive.py tests/integration/test_holder_run_outcome.py tests/integration/test_holder_source_migration.py --basetemp "build/pytest-$acceptanceRun-integration" --junitxml "build/$acceptanceRun-integration.xml"
```

运行前核实独立服务实际server_uuid/端口，不能因 `EMPIRE_INTEGRATION=1` 就假设它自动选到13348：现有通用fixture未设置 `EMPIRE_TEST_MYSQL_SETTINGS` 时可能继承生产实例连接再建私有库。必须显式指定核实后的独立测试配置，保留原环境值并在本轮结束恢复，不覆盖用户日常网络/任务设置。保护不等价：通用集成fixture当前以engine URL隔离，D安全helper另含真实会话和SQL语法验证，不能把后者保障写给所有旧测试。

不要把 PrivateStorage 独立smoke放进现有集成autouse fixture再关闭guard求通过；两套不同独占库guard应保持隔离执行。任何pytest错误、超时或清理错误先处理，不直接进入真实采集/容量/发布。

公共回归按影响选择至少覆盖真实风险：`tests/test_archive_queue.py`、`test_fingerprint_versions.py`、`test_ingest_reservations.py`、`test_unit_prefetch.py`、`test_prefetch_budget.py`、`test_all_collector_prefetch.py`、`test_collection_control.py`、`test_manager.py`，以及对应 `tests/integration/test_prefetch_pipeline.py`、`test_archive_fairness.py`。完整发布会再次运行正式全量集合；定向测试不能替代该步骤。

## 6. 真实来源验收：随机30、固定反例与诚实缺口

### 6.1 先判定适用性，再确定冻结样本

新增或实质修改采集插件（含解析修复、请求/恢复/消息契约）适用随机30股。纯组织迁移必须逐项给出代码/契约/输入输出/恢复等价证据及有限正式E2E，不能只写“搬文件”；不能在看到失败后才把实质修改重新归类成不适用。非股票来源、不足30池或按指数/日期/规则采集要写明粒度与替代验证，不声称满足30股票门槛。

冻结完整适用池及摘要、筛选规则、随机算法、显式种子、30个不同随机代码、固定名单和合并名单。固定已知失败证券额外加入，不替代随机；保留失败样本，不剔除换样。每次重试另写新报告，原抽样及失败保留；重新抽样只能作为另一轮证据，不能抹掉上一轮结论。

开发来源请求统一共享下载/代理/频控，默认 `use_proxy=true/proxy_fallback=true`。严格代理验收要求真实请求全部走代理；即使开发回退允许且链路成功，direct/fallback非零也不计代理准入。不得直接HTTP请求或修改用户已保存任务策略来缩短验收。

### 6.2 D安全命令（草案通过前置验证并集成后才运行）

```powershell
.venv/Scripts/python scripts/smoke_source_storage_sql.py --test-mysql-settings $testMysqlPath --security 601139.SH --output "build/$acceptanceRun-sql-smoke.json"
.venv/Scripts/python scripts/verify_ths_holders.py --test-mysql-settings $testMysqlPath --random-count 30 --seed 20261019 --proxy-only --output "build/$acceptanceRun-holders-source.json"
```

第一条仅合成数据SQL正向验收，不请求来源：实际 initialize_database/require_schema、共享设置、三栏两报告初始/修订、Redis→统一归档→browse/detail/audit。要求SQL SMOKE PASS、合成标识、source_requests=0、sample_30_met=false、声明SQL成功计数、pending=0、全部清理通过。不能拿它替代第二条。

持有人验证器固定反例包含 `300398.SZ`、`601515.SH` 及其代码中的完整固定名单；执行前核对名单没有删减。已知来源缺口包括 `300398.SZ/2023-12-31`、`601515.SH/2024-06-30` 的空名债券。不得补造名称、白名单跳过、剔除报告或把source_gap写成not_published/complete。

允许出现诚实的分层结果：`pipeline_verified=true` 表示本轮有效记录和缺口证明完整经过正式通路；`acceptance_complete=false` 表示范围仍有来源缺口；整个严格CLI必须FAIL。`sample_30_met` 即使某子集满足，也不能覆盖固定反例或整轮失败。报告需保留缺口定位、首缺口连续断点、有效后续证券、无伪完整manifest、正式audit/准备结果与待归档0。

来源质量与采集完整性分别判断；金额矛盾/缺公布日期等可影响历史信号用途，不通过补零或删除异常值让分析变绿。基础估值分析与严格历史回放的适用标准按既有契约，不随迁移擅自收紧/放宽。

E财报命令形态如下；必须核实当前 `KINDS` 枚举和已知失败固定名单，必要时通过 `--codes` 明确增加，不能假设默认已经覆盖全部历史问题：

```powershell
.venv/Scripts/python scripts/verify_ths_statements.py --test-mysql-settings $testMysqlPath --random-count 30 --seed 20261019 --proxy-only --output "build/$acceptanceRun-statements-source.json"
```

当前财报草案复用共享helpers，CLI并不自动强制最低30或代理必选；因此执行记录和审核必须明确核对这些参数与实际计数，不能单看exit0。在后续增强该约束前，不把它描述为已实现的自动门禁。

## 7. 私有资源、取消和恢复验收

1. 生产MySQL只允许已审的只读股票池/设置/身份查询；测试显式13348并核实际server_uuid不同。host/port文字不同不能代替实例隔离。
2. UUID数据库/Redis namespace必须本轮独占。记录run_id、database、namespace、server_uuid、owner摘要；秘密owner原文只在本地 `.ownership.json`，不提交、不公开。
3. guard必须核真实会话database/server_uuid，并限制正式SQL；初始化仅当前schema精确语句。拒绝跨库、USE、多语句、隐藏注释与未审DDL；不得为通过正例改成通用放行。
4. 失败/取消先停止全部生产者与插件，确认上下文/SQL lane/请求/预取已回收；只有确认关闭后才按owner/锁/实例清理本轮资源。关闭不完整则保留guard、连接和锁引用，标记remaining/unknown，不破坏仍可能运行的数据。
5. SQL与Redis独立清理，某一失败不能跳过另一项或原错误。DROP前验证owner和同连接GET_LOCK归属；Redis仅精确私有前缀并核owner；禁止FLUSHDB/FLUSHALL、扫库猜测删除、改RouterProxy目录或删共享锁。
6. 先完成清理、源/配置摘要再核实、最终报告原子落盘，之后才可打印PASS。清理失败、报告保存失败、输入漂移均使整轮不能通过，业务中途成功不能覆盖它们。

恢复示例仅针对同一已记录资源，输出使用新文件：

```powershell
.venv/Scripts/python scripts/verify_ths_holders.py --test-mysql-settings $testMysqlPath --cleanup-only --run-state "build/原报告.json.ownership.json" --output "build/$acceptanceRun-cleanup.json"
```

必须先核实原进程已停止，且工具按实际锁/owner证明归属。恢复命令不能重新初始化/采集，不能宣称完成随机30；缺owner、实例改变、仍持锁、状态未知时保留资源并记录阻塞，不人工清库。已处理错误记录仅在修复和验证完成后按登记的确切错误ID清除；只读发现、一次成功或来源缺口不等于错误已修复。

## 8. 容量：按实际绑定重测，不能刷新旧hash

每次最后实现/类型/测量工具/fixture修改后，重查所有 active measured 设计卡的文件绑定。路径移动也会失效；不能把旧报告改成新路径/hash后继续用旧数字。旧报告原样保留，新报告先真实执行、核清理与绑定，再更新对应设计卡 `capacity.evidence`。

| 阶段 | 必须重新核验的能力/入口 | 关键边界 |
| --- | --- | --- |
| D | `measure_holders.py --report <新文件>`；`measure_ths_capital.py --report <新文件>` | 持有人2500发行主体×4期，资本700证券；原阈值/fixture不缩减；共享HTML改动已影响资本 |
| E2 | `measure_indices.py --output`、`measure_index_prices.py --output` | 指数目录/成员与行情status/year各自绑定和实际集合 |
| E3 | 按实际diff重查 | 保留公共preparation路径后没有仅因此移动产生的额外失效；不是免行为测试 |
| E4 | `measure_preview_queries.py --output` | 七种kind必须各有样本；100000同秒点、真实日期与环境；空/缺/重复种类失败；原旧v1写入实验不得直接当当前v2入口 |
| E5 | 分红当前SQL只读诊断与完整新方案 | `measure_existing_capacity.py --subject dividends`即使诊断完成也exit2；缺source_rows/planned_periods不能完整通过；需实现并审阅当前完整或明确新协议 |
| E6a | THS资本再次新测 | D报告不覆盖最终路径/表权威接线 |
| E6b | 上市/状态各测量器及新BSE完整合成入口 | BSE1000行集合/内容、pending=0、ux_alias_security；import_ms≤2000、read_ms≤100、allocated_bytes≤1048576；无来源请求，不证明官方当前映射完整 |
| E6c～g | names/ST、unlocks/industry、performance/shareholders、repurchases、rules对应 `measure_*.py --output` | 各设计卡保留原样本/SQL协议/阈值；每批逐份新测，不能总报告代替 |

完整逐表清单在交接资源 `build/de-composition-20261019/capacity-stage-plan.md` 和 `capacity-impact.json`；它们是预测，不替代实际已集成树的重新核查。原17份报告最终均可能随所属业务迁移失效，E0是否触发取决于是否提前改变bound文件。

所有容量入口先审：真实实例身份、UUID所有权、逐连接归属、生产只读范围、SQL语句、失败/取消清理、输出不覆盖、PASS在清理之后、真实版本/端口/刷盘参数。未审工具不因名为measure就被视为安全。默认指向旧证据的工具必须显式给新输出路径；禁止直接运行有意留库的历史临时脚本补测。

容量报告至少记录：schema及协议、开始/结束时间、源与实际工具/fixture/DDL绑定、实际服务参数、样本规模与业务集合/摘要、所有原始计时/统计、limits、correctness、cleanup、异常和最终结果。未测项写未知/未完成，不能用0；原始环境不完整时明确比较限制。容量与T3、随机30实采、生产覆盖是四种不同证据。

## 9. T3：冻结同机性能复验

权威协议为 [architecture-performance-protocol-2026-10-19.json](../evidence/architecture-performance-protocol-2026-10-19.json)，冻结基线为 [architecture-performance-baseline-2026-10-19.json](../evidence/architecture-performance-baseline-2026-10-19.json)。禁止后测修改协议、阈值、baseline、`architecture_benchmark.py`、`architecture_benchmark_data.py` 或 `release_lock.py` 来凑通过。

核实的现行协议：冷进程warmup1/repetitions7；热项warmup3/repetitions15；九指标 `cold_declarations`、`assembly`、`news_first`、`news_next`、`news_search`、`holders_browse`、`holders_detail`、`news_ui`、`holders_ui`，各median与p95共18项。每项须≤`max(基线×1.25, 基线+绝对噪声底限)`；cold/assembly/query/ui底限分别100/2/1/5ms。不得只报平均或删慢样本。

固定数据为新闻20000行、每屏50、正文512字符；股东100证券×10期×3栏、当期10与退出2、每屏20。13348私有MySQL、原DDL和flush=2、SQL lane两worker/16等待、单并发；UI离屏scale1、1280×800与正式style。机器/CPU/OS/Python/依赖、字体、协议/harness/fixture/DDL摘要、版本和参数须可比。

正常关闭桌面及日常采集，停止其他测试/扫描/数据库操作/构建；T3本身也受发布所有权约束。不要与任何正在运行的发布门禁或发布后桌面核验并行。独立测试配置不加载生产默认值。测量前后源输入不能变化，私有schema精确清理。

```powershell
.venv/Scripts/python scripts/architecture_benchmark.py measure --protocol docs/evidence/architecture-performance-protocol-2026-10-19.json --test-settings $testMysqlPath --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output "build/$acceptanceRun-t3.json"
```

`measure` 的test-settings格式以当前冻结脚本读取器为准，不假设与其他helper的JSON顶层完全相同。执行者先读格式、核服务身份；格式不同则准备受控私有输入文件，不修改harness适配。已有冻结baseline时不调用freeze替换它。

审核同时检查18项比较、全部原始samples、correctness、cleanup、environment和输入hash。噪声干扰必须记录当次失败原因并完整重跑，保留失败轮次，不挑最快一轮；超阈值修复或缩减范围。新机器/新依赖不能自动沿旧基线宣布通过；需要独立的新协议/基线阶段。离屏QImage不是实际窗口，冷进程不是冷磁盘，本机合成查询不是网站吞吐或断电持久性。

## 10. 文档、正式发布与真实桌面

### 10.1 文档审阅在最终实现之后

先修改用户行为/数据说明、覆盖关联、生命周期及实现状态。纯类型或位置变化也逐功能说明为何用户正文不变，不能只刷新整体摘要。只更新确实当前的说明，历史evidence不改写。

```powershell
.venv/Scripts/python scripts/documentation_contract.py review --note '本批实际审阅的入口、行为、数据范围和限制'
.venv/Scripts/python scripts/documentation_contract.py check
.venv/Scripts/python scripts/verify_documentation.py
.venv/Scripts/python scripts/verify_database_design.py
.venv/Scripts/python -m pytest -q --tb=short -rs tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py tests/test_storage_help.py --basetemp "build/pytest-$acceptanceRun-docs" --junitxml "build/$acceptanceRun-docs.xml"
```

需要 `--unchanged-reason` 或逐 `--unchanged FEATURE=REASON` 时填写真实的逐功能依据，不使用上例泛化文本作为正式note。缺用户正文不是“技术改动”自动豁免；最后又改源码/正文会使审阅失效。

### 10.2 唯一正式发布

1. 形成干净、可追踪的本批提交，核对远程/目标main及已授权推送范围；不混入其他任务更改。用户要求推送的批次核对push实际成功与远程commit一致，失败不能写已同步。
2. 正常关闭Empire，等待采集/归档/数据库连接退出，保留配置/偏好摘要和待归档事实。不强杀数据库，不删单实例/发布锁。
3. 保留显式测试实例配置环境，确保集成使用已核实13348；运行 `./verify-release.ps1`。直接build也走同门禁，不另调PyInstaller或手动替换dist绕过。
4. 保存本轮run目录、原始步骤日志和JSON、JUnit、输入清单、依赖/容量/UI/包内证据、publication journal。失败保留旧包和现场；恢复使用受控入口。
5. 仅journal确认为committed/passed且最终产物/输入/证据一致，才能写“已发布”。这仍不等于真实桌面通过。

```powershell
.\verify-release.ps1
```

发布默认门禁包含完整pytest、独立容量与四档DPI、真实声明构造及搬移smoke。每一步有自己的实际退出码和输出完整性；不能只摘最后的PASS。`build/release-report.json` 是便捷副本，审核本轮 `build/releases/<release_id>/publication.json` 及retained evidence，避免读到另一轮的共享文件。

### 10.3 同代码、同包的最终实际核验

| 检查 | 操作与证据 | 不能代替它的东西 |
| --- | --- | --- |
| 身份 | 包内build_manifest、Git commit/dirty/source/release_id、依赖与preparation摘要、最终EXE及安装文件树与journal一致；运行状态构建标识一致 | 开发源码启动、旧包截图或仅同版本号 |
| 配置/偏好 | 根与程序目录config逐字节保留，偏好保留；从如 `C:/Windows` 的不同cwd运行正式EXE，默认仍读程序同目录配置 | `check-config`只验证语法，不能证明真实连接 |
| 连接/正式查询 | 同一安装配置真实Redis/MySQL连通；本批代表性正式查询返回预期业务键、内容、分页/空态 | 仅ping、原始SQL计数或开发mock |
| 页面/导航 | 可见EXE工作台、数据目录、本批页面与帮助；新闻正文、持有人三栏及相应业务实际数据；窄窗口/滚动/文字可读 | offscreen截图或package-smoke空外壳 |
| U1 生命周期 | 单页停用不关闭采集/查询；停采集器仅相关任务不可用，控制器、历史与其他任务继续；依赖者阻止共享服务直接停用 | 认为“万物插件”意味着任意停用均无影响 |
| U2 草稿/交互 | 页面按需创建，切页取消只读请求；未保存编辑经刷新/切页行为符合设计，稳定选择/滚动保留；滚轮不改变可变值控件；提交写命令不因切页取消 | 只看页面能打开 |
| U3 稳定身份/设置 | 与上列同包身份、异cwd配置、正式查询和页面/导航一并验证；原任务ID/已保存策略、适用next_due与插件偏好保持；不为测试改日常代理开关或删除断点 | 新建一套干净用户设置 |
| 正常关闭 | 可见关闭提示，等待窗口与后台任务正常退出；记录随后队列事实，未完成消息保留正式重放 | 强杀EXE后宣称资源已清理 |

记录方法、时间、真实窗口/产物路径、实际操作与结果。不同时间读取不冒充原子快照。可记录图片哈希/本地路径，但不得包含凭据。当前能力若无法观察/操作真实窗口，就标未验证并保留该退出项，不能编造可见桌面结果。

发布后用户日常任务可能继续新增消息；本轮严格实采的pending=0是特定验收范围，不等于之后全局永远为0。最终关闭时若有消息，记录项目/时间和保留重放，不手工清空使统计好看。真实GUI打开会恢复原用户计划，应提前了解共享影响，仍尊重已有正常关闭授权。

## 11. 证据字段与审核流程

### 11.1 四种身份不可混成一个hash

| 身份 | 权威来源与用途 | 审核要求 |
| --- | --- | --- |
| 完整发布输入 | release管线冻结的完整代码/测试/SQL/依赖/脚本/资源/文档及Git | 每阶段前后相同；生成输出独立绑定，真实配置单独保护 |
| 业务实采输入 | source_verification的source_sha256及input_files、selection摘要 | 验证期间源/两个配置文件不变；不等于完整发布输入hash；跨提交复用必须逐项证明业务未变 |
| T3输入 | benchmark的source/protocol/harness/fixture/DDL及环境 | 冻结协议与样本、同机同依赖可比；不能用release hash替代指标正确性 |
| 容量输入 | 各报告bindings、实际测量器/helper/fixture/SQL metadata/DDL | 所有当前文件hash精确匹配；移动/接线/类型修改后按真实依赖失效重测 |

这些摘要算法和范围可能不同，不能要求字符串彼此相等；应建立明确的文件/提交/执行关联，并核对各自前后不变。报告的手写描述不能替代机器生成的输入清单。

### 11.2 已有报告的实际字段审核

| 报告 | 必查字段/证据 |
| --- | --- |
| pytest | 实际命令/环境/开始结束、exit_code、JUnit tests/failures/errors/skipped、逐skip理由、完整日志；不能只保存总passed数 |
| architecture | schema、passed、errors、new_debt、existing/retired_debt、module_ownership、dependencies、limitations；逐条核owner真实性和旧债务去向 |
| assembly | 原baseline/order baseline摘要、受审mapping、业务语义及顺序精确比较、维护入口验证；只比较数量不够 |
| 安全来源 | run_id、subject/mode、source_sha256、input_files、selection全池/seed/random/fixed/selected及摘要；实际路由次数；每报告业务键/内容摘要、SQL证明/manifest/audit/preparation、pipeline_verified/acceptance_complete/strict_proxy_verified/sample_30_met；errors、remaining、六项cleanup |
| SQL smoke | 顶层mode=sql_positive_smoke、source_requests=0、sample_30_met=false、sample_30_applicable=false；results.sql_smoke.synthetic=true；实际CREATE/metadata/DML覆盖、初始/修订集合正文相同、pending=0、清理全部成功 |
| T3 | schema、passed、protocol/harness/source/fixture/ddl摘要、机器/依赖/MySQL/字体、全部samples、median/p95与comparison、correctness、cleanup和limits |
| 容量 | 当前schema、全部原预算/实际测量、样本/集合、bindings、真实环境、cleanup、errors/limitations；局部诊断not_capacity_gate_evidence不能成为设计卡通过证据 |
| 发布 | 本轮publication committed/passed、commit/dirty/source、retained evidence摘要、输出日志完整/退出码、EXE/安装树/包内清单、配置保留、恢复记录 |
| 实际桌面 | 绑定同release/EXE、获取时间、可见窗口方法、入口/动作/结果、实际查询范围、配置/偏好、正常关闭和未完成项 |

共享source helper现行cleanup字段为 `shutdown/sql/redis/sql_lock/connections/instance_lock`，全部须true；`remaining.sql/redis`须false，unknown不是false。数据内容/路由正确但cleanup失败仍整轮失败。各容量helper字段名称可能不同，按实际schema逐项映射，不能硬套一份JSON让验证器误读。

### 11.3 证据审核步骤

1. 逐项读取原始报告和对应完整日志，确认该报告来自本轮真实命令、不是模板、草案或旧文件。文件创建时间本身不证明执行过。
2. 核对工具/fixture/输入/协议/依赖/服务身份与本次实际实现；审核报告绑定的文件是否在产生后变化。
3. 从JUnit或原始测量重算必要计数/统计/集合摘要，核对消费者看到的字段，不只信顶层passed。
4. 核对异常、取消、清理、输出保存、剩余资源和skip；失败要保持原分类，来源gap/网络失败/代码缺陷分开。
5. 核对范围：适用股票池、证券/日期/页面、质量与用途、有限抽验与实际全量归档不能互相冒充。
6. 审查身份与行为迁移表、旧路径退役、文档关联、容量失效和公共消费者回归是否完整；缺项停止扩大阶段。
7. 审查完整发布与真实桌面是否同包，提交/远程是否一致。新增事实更新本轮记录，不覆盖历史失败。
8. 由另一轮只读审阅或独立代理检查关键结论时，记录具体核对对象和发现；独立审阅不能代替实际执行。最终所有适用退出项都具证据才将阶段标完成。

## 12. AI统一结果记录模板

以下为**人工汇总模板，不是任何现有门禁输入schema**，不能提交给发布/设计验证器冒充机器报告。默认全部未运行，保留null；执行者填真实结果并引用原始报告，不手改原始报告的passed或hash。模板不包含凭据/owner原文。

```json
{
  "record_kind": "architecture_stage_acceptance_summary",
  "schema": 1,
  "stage": "D-or-E-substage-or-F",
  "run_id": "待填写本轮唯一标识",
  "status": "not_run",
  "scope": {
    "goals": [],
    "non_goals": [],
    "affected_features": [],
    "affected_contracts": [],
    "retired_paths": [],
    "persistent_contract_changed": null
  },
  "inputs": {
    "base_commit": null,
    "tested_commit": null,
    "dirty": null,
    "formal_input_report": null,
    "business_source_report": null,
    "protected_harness_hashes": {},
    "draft_manifests_applied": [],
    "unrelated_changes_preserved": []
  },
  "environment": {
    "shared_operation_owner": null,
    "desktop_normally_closed": null,
    "test_server_uuid_verified_different": null,
    "test_port": null,
    "owned_database": null,
    "owned_redis_namespace": null,
    "config_preserved": null
  },
  "criteria": [
    {
      "id": "填写总方案验收ID",
      "applicability": "undetermined",
      "reason": null,
      "status": "not_run",
      "commands": [],
      "started_at": null,
      "finished_at": null,
      "exit_code": null,
      "evidence": [],
      "assertions_observed": [],
      "skipped_or_unknown": [],
      "failure_and_next_action": null
    }
  ],
  "source_acceptance": {
    "status": "not_run",
    "scope": null,
    "pool_digest": null,
    "seed": null,
    "random_codes": [],
    "fixed_codes": [],
    "proxy_requests": null,
    "direct_requests": null,
    "fallback_requests": null,
    "source_gaps": [],
    "pipeline_verified": null,
    "acceptance_complete": null,
    "sample_30_met": null,
    "pending": null,
    "raw_report": null
  },
  "capacity": {"status": "not_run", "invalidated_reports": [], "new_reports": [], "limits_unchanged": null},
  "t3": {"status": "not_run", "protocol": null, "baseline": null, "report": null, "all_18_checks": null},
  "cleanup": {"status": "not_run", "raw_report": null, "remaining_resources": [], "recovery_action": null},
  "documentation": {"semantic_review": null, "contract_report": null, "unchanged_reasons": []},
  "release": {"status": "not_run", "release_id": null, "publication": null, "exe_sha256": null, "tree_sha256": null},
  "actual_desktop": {"status": "not_run", "release_id": null, "observations": [], "normal_close": null},
  "git_delivery": {"commit": null, "main_contains_commit": null, "remote_commit": null, "push_verified": null},
  "review": {"status": "not_run", "reviewed_evidence": [], "findings": [], "resolved_findings": []},
  "limitations": [],
  "uncompleted_items": [],
  "next_stage_allowed": false
}
```

每个 `evidence` 至少登记相对路径、文件SHA-256、产生它的命令与时间、输入身份、作用范围和明确结论。公开提交只保留脱敏必要证据；成功HTML/完整业务正文、连接文件和ownership秘密不复制进docs。

## 13. 失败分流与最终交付

| 情况 | 下一步 | 禁止行为 |
| --- | --- | --- |
| 草案不兼容实际前像/新API | 停止应用，按实际已验收前批重新定向合并、保留其他变更，补影响验证 | 整树覆盖、恢复旧公共路径转发层凑测试 |
| 语义/集合/身份差异 | 最小反例定位，修复本批或缩减范围；消息与用户数据保留 | 用相同条数、成功请求或AST等价抹去差异 |
| 来源gap/质量不足 | 保留原值和缺口，按实际范围报告partial/failed；明确下一步或适用边界 | 换样、填零、伪造标识、删失败证券、标complete |
| 清理/取消/归属未知 | 保留资源和秘密恢复记录，核实原进程/锁后走精确恢复 | 无条件扫库/清Redis/删除锁/强杀数据库 |
| 容量/T3超限 | 保留样本和环境，修复、缩减或按原条件完整重测 | 调阈值、缩样本、只报最快轮次、更新旧hash |
| 门禁失败或输入改变 | 修复后重新建立受影响证据，运行同一正式入口 | 手写passed、跳阶段、手动换dist、复用旧XML |
| 包通过但桌面失败 | 正常关闭、保留失败证据，修复后重走受影响门禁/发布和真实窗口 | 将离屏smoke说成真实部署验收 |

阶段最后交付必须逐项对应用户要求，包含：本批真正实现、主路径和退役、稳定身份/依赖变化、实际命令和结果、skip/不适用理由、实采范围与缺口、容量与T3、文档审阅、完整release身份、配置/偏好与真实桌面、提交/main/远程、未完成项和下一步。

所有适用退出项通过才允许下一阶段；如果当前任务只授权方案/手册，则交付边界是文档，不应用候选。后续获得实施授权时常规开发、测试、正常关闭/重开及既有范围内发布自主完成，不新增逐步审批。缺失信息实质改变业务范围、必须新增权限或涉及未授权数据丢弃时才提出具体问题，并继续不依赖答案的工作。
