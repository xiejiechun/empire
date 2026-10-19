# C 收尾、D 股东样板与 F 共享治理实施手册

本文是后续实施指令，不是通过记录。先读 [交接入口](README.md)、[实际状态](status.md)、[统一验收](acceptance.md) 和 [E 逐业务实施](e-implementation.md)。执行者必须从 `status.md` 与对应原始报告确认当前阶段；不能把本文出现的候选、测试名称、命令或静态证明当成已实现保障。

项目根目录以下示例为 `D:\project\empire`。所有 `src/`、`scripts/`、`tests/`、`sql/`、`docs/`、`build/` 路径均相对此根目录。迁移最终方案以正式源码、[已批准实施方案](../architecture-evolution-plan.md)、[开发流程](../development-workflow.md)、本目录的 `planned-migrations.json` 和阶段验收为权威；忽略的 build 草稿是可用的复核材料，不是另一份运行时权威。

## 0. 共同执行规则和材料核验

### 0.1 取得实际前像，避免并发覆盖

每一阶段开始前完成以下动作并记入阶段记录：

1. 记录 `git status --short`、当前分支、`git rev-parse HEAD` 和已有未跟踪文件，明确本轮负责的修改。其他任务的修改不还原、不顺手提交。
2. 确认没有运行中的 release、PyInstaller、benchmark、集成测试、实采或 SQL 维护。已有 C 门禁进行中时继续等待其自然完成；不得边打包边修改正式正文、源码、测试、SQL、配置、工具、依赖或构建资源。
3. 只有取得源码编辑所有权后才应用候选。真实桌面、数据库和发布操作串行执行。需要停桌面时正常关闭，等采集/归档/连接退出；完成后恢复可见桌面。不能强杀数据库、删除他人锁或绕过单实例。
4. 本轮仅使用程序目录 `config.toml`；不打印其正文或密码，不改用户日常代理策略。独立测试设置显式提供，实际服务必须与生产不同。保留生产待归档和业务数据，禁止清空共享 Redis、猜库名 DROP、借组织迁移执行生产 DDL。
5. 对每个拟改正式文件保存原始字节、SHA-256、候选字节和来源；新增文件记录“原本不存在”，删除文件保存完整前像。共享文件采用 AST、JSON 键或精确段落合并。前像不符先查清差异并重基，不能用整棵草稿 tree 覆盖当前仓库。
6. 回滚只针对本轮已证明归属的变更，且目标仍等于本轮写入字节；遇到并发变化保留文件并记录冲突。不得使用 `git reset --hard`、笼统 `git clean` 或递归删除共享 build 来回滚。

以下变量仅在对应阶段获得执行窗口后设置。环境配置路径须先由执行者核实，不读取或显示其内容。`$stageTag` 每次重试重新生成，失败报告保留。

```powershell
Set-Location -LiteralPath 'D:\project\empire'
$stagePython = (Resolve-Path -LiteralPath '.venv/Scripts/python.exe').Path
$stageTag = 'd-holders-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
$stageTestSettings = $env:EMPIRE_TEST_MYSQL_SETTINGS
if ([string]::IsNullOrWhiteSpace($stageTestSettings)) { throw '先指定已核实的独立13348测试MySQL配置路径' }
$stageTestSettings = (Resolve-Path -LiteralPath $stageTestSettings).Path
function Invoke-CheckedPython([string[]]$Arguments) {
    & $stagePython @Arguments
    if ($LASTEXITCODE -ne 0) { throw ('检查失败，保留本轮输出：' + ($Arguments -join ' ')) }
}
```

`EMPIRE_INTEGRATION=1` 是执行集成的开关，不是已验证隔离的证明。所有相关集成运行前显式设置 `EMPIRE_TEST_MYSQL_SETTINGS`；不允许缺省回生产实例。私有 SQL/Redis 的归属、实际 server_uuid、清理和待归档状态按 [统一验收](acceptance.md) 逐项核实。

### 0.2 当前候选目录与身份

以下为交接时读取的候选身份；表内 SHA 是整个 manifest 文件的 SHA-256。重新准备后须重新保存清单，并解释语义差异，不能只更新 hash。候选过时不意味着丢弃其新增测试或已经修正的安全行为。

| 候选 | manifest / 其他身份 | 用途与限制 |
| --- | --- | --- |
| `build/de-composition-20261019/d-only/` | `manifest.json`；由 C capture 与 composer 共同约束 | D 路径、声明和共享文件整合前像；不是最终 D 全部修改 |
| `build/d-holders-draft/` | `manifest.json` = `7dec9cd44b48c9aa02b007b40107bc29b6c841b2b69f7d22c0197e4d417c6ec1` | 原始八模块搬迁、43目标草稿；原稿基于更早 C，优先审阅实际 C 后整合 |
| `build/holder-verifier-draft-20261019/` | `manifest.json` = `fe2aaeac9e89d60e2ecb91cc330274a6ad2af95dd42f50956aa02170a4bd46f6` | revision 2；D 共享私有存储/生命周期与股东验证器；E 财报 companion 另阶段应用 |
| `build/d-holder-types-20261019/` | **没有 manifest**；`static-proof.json`，目标 contract SHA `12361976c7db0065bcbc705a8ed62bf74ae8ca52c14df22de258594ba8d354e3` | 9个函数注解、RawReport/RawGap；应用前补本轮前像清单，不能冒称已有manifest |
| `build/capacity-safety-draft/d/` | `manifest.json` = `fb61457b58ea7bfca5eb8f0d443e365e2f7fbf431fb2d61b6da510b641fc23ac` | D 只改 holders/THS-capital 两工具；共享新文件在同目录上一级 `tree/` |
| `build/capacity-safety-draft/e/` | `manifest.json` = `779d9cb502dec07b7f694442d25c7eed414d59017d4f99cc0460dbd9cec37d50` | 最终 E 三工具前像；不提前把 preview 工具改入 D |
| `build/d-sql-positive-smoke-20261019/` | `manifest.json` = `9ab757d05811b334d3746c8dc1ce66d6d06c1b60e0bd47fe8bba88ee2e73b523` | 新 `scripts/smoke_source_storage_sql.py`，真实 SQL 正向冒烟，不是来源实采 |
| `build/d-holder-documentation-20261019/` | `manifest.json` = `f12168dd5ef0315ca9109c308aa208e282a9e695b7723c8f022293ba75d3d46c` | 5文件15处精确正文编辑；已含 verifier 的 D 文档段，勿重复应用 |
| `build/e-readme-locality-draft/` | `manifest.json` = `82f79c696b9ed765dc02cac669d8fa3bb5d4819d906298339257edca01e2b506` | 最终 E 25包定位，12新README；已有文件主要追加，保留实际 D/E 新正文 |
| `build/f-docs-preparation-20261019/` | `manifest.json` = `033798a8373d90cd8c357e9b8447f3f5c94ea9ae31b1f83e63322df325bd7f9a` | 164目标旧正文候选；必须从最终 E 正文重新提取，不得照搬旧文章 |
| `build/f-public-types-20261019/` | `manifest.json` = `2dcec112c3bba9fbb92fb0a9e3db3f820537de4236b9a0852635dfe8610e0c05` | 五个公开边界类型增量，公共 preparation 仍在 contracts |
| `build/f-metadata-edits-20261019/` | `manifest.json` = `1a4cb2caabd448bf7807e86bfa04cadbaefeff59c84bdb743eff5b68cd1d7054` | 三项精确 owner/role 修改，不整体覆盖架构 policy |
| `build/f-shared-gate-preparation-20261019/` | `manifest.json` = `50105e5e61e4a3cd404de73bbeee1c5f6eeadeaefa4c4748847860e6d5708c74` | 通用 kind 门禁，替换 E 两条窄规则；另追加测试文本 |
| `build/f-impact-preparation-20261019/` | `manifest.json` = `dd312362a134eef3a1799796db780c33d527e371401da47c2b3dde9a9ffeba66` | 影响报告及测试，选择性反馈不替代发布全量 |
| `build/f-test-cost-preparation-20261019/` | `manifest.json` = `7a6021b84c9091f9346d9ae7fdc7fddade5354c56829580e37c6bdc3e77e2d41` | 七个测试侧目标，先做实验；无收益不采纳 |
| `build/m1-locality-drills-20261019/run.py` | 本轮执行前保存该文件SHA与最终src/sql输入清单 | 三类独立副本演练；默认不执行，需 `--execute` |

核对目录存在、manifest 自身摘要、每个 target/preimage 摘要、退役清单和草稿未执行标记。可用 `Get-FileHash -Algorithm SHA256 -LiteralPath <清单文件>`；不要通过重新生成来掩盖意外变化。文档中的静态检查只涉及 AST/字节/路径，不是运行验收。

### 0.3 build 草稿缺失时的规范重建

不要停在“找不到 build”，也不能编造草稿。按如下顺序重建并保留新证据：

1. 从 Git 取得上一阶段**实际通过**的正式提交、迁移映射、assembly 基线、架构 policy、业务规则及文档；核对 [实际状态](status.md)。`planned-migrations.json` 只定义计划映射，不表示目标文件已经存在。
2. 读取本章各阶段目标、现有业务 API/测试和唯一公共基础设施。对已有函数先保存源码、AST、导入与调用方清单；根据计划逐个迁移，不从记忆重写业务逻辑。
3. 在新的本轮 build 目录生成候选、逐文件前像/新像清单、退役映射、键/段落合并计划。对安全工具按照本文列出的边界和反例重建实现；没有运行过的工具必须先测试，不能只实现外观相同的CLI。
4. 重新执行该阶段全部适用验收；旧静态证明只用于比较，不能作为新实现通过证据。类型/文档/测试成本工具按其职责重建，禁止建立旧路径转发或第二正式流程。
5. 不能恢复的实验原始基线不得补造。冻结 T3 原基线/协议缺失时先从 Git 的正式 evidence 恢复；无法恢复时报告性能结论缺证，并在任何新测量前重新预登记条件，不以测后数值设门槛。

## 1. C：完成当前发布与新闻样板收尾

### C-01 核对 C 门禁身份（当前已完成，接手先读状态账本）

当前已知 C 代码冻结提交为 `81e147f35ba6af89b8b08219fe533130c875313c`，第二轮 release ID 为 `8fbd5bd7a9cf460a9b82022b7e643f1d`；第一轮 `4a1e7b817c264d20b61f4db85352c85d` 为失败历史。该轮现已完成发布和实际验收，结论见 [实际状态](status.md)。以下保留收尾核对步骤；接手者有对应真实证据时不重复发布。

逐项核对：

- 当前源码、测试、SQL、工具、文档与 `build/releases/<实际run>/inputs.json` 相符；冻结后修改又恢复字节也会使当前发布身份失效。
- 保留 `81e147f` 的数据库设计门禁反例修复：测试通过真实新增 `DatasetContribution` 驱动正式 catalog 检查。后续 D/E/F 不得恢复旧 `gate.builtin_catalog()` 或只 mock 普通字典的过时测试。
- 全量 pytest、打包、package smoke、发布切换是不同步骤；某一步通过不能提前写其他项通过。
- 只跟进同一运行，不另起 release。失败时保留原日志、JUnit、publication journal、inputs 和错误定位；修复后新建一轮，不修改旧 run 状态。

### C-02 检查真实发布提交结果

门禁自然结束后，核对 `build/release-report.json` 指向本轮；`build/releases/<run>/publication.json` 必须为同一 run 的 `state=committed`、`passed=true`。核对其提交、source/input、测试/依赖报告、包及 EXE 摘要，确保安装目录 `dist/Empire/` 与本轮产物一致。

配置保留验证只比较摘要/字节相等，不输出内容：项目根 `config.toml`、`dist/Empire/config.toml`、插件偏好及原任务/网站设置均应保持。真实配置不纳入Git或公共分发。安装失败或目录切换中断按 publication journal 和 `verify-release.ps1 -Recover` 的正式恢复入口处理；恢复不是重新通过验证，也不能在仍运行的发布旁并行执行。

### C-03 正式 EXE 只读连接和真实桌面

按 [统一验收](acceptance.md) 使用本轮正式 EXE，分别记录：

1. 从 `C:\Windows` 等不同工作目录启动，仍读取 EXE 同目录配置；Redis/MySQL 真实连通。不能用源码解释器的成功代替EXE。
2. 正式股票查询和新闻查询确有记录；只读服务按正常生命周期退出，不启动第二采集器/归档器以获取查询结果。
3. 可见正式窗口实际显示本轮构建身份、连接状态、新闻内容与原导航。检查新闻检索、详情、正常关闭及重开；截图、窗口标识、时间和观察文字关联本轮身份。离屏测试不是这一项。
4. 未保存草稿、页面按需创建、原插件偏好及任务配置保持。退出等待正在运行的合法工作完成，不强杀共享服务。

`build/architecture-evolution-20261019/post-release-c-accepted.json` 只能由这些真实观察形成。不能先写 `passed_read_only=true` 或 `actual_desktop=passed` 再补操作。公开 evidence 删除凭据和私有恢复token；本地恢复文件保留原样。

### C-04 记录与 D 准入

更新本轮事实记录、实现状态和交接 `status.md`，区分代码提交、测试、发布、只读数据抽验、真实桌面。若只新增事实文档，按文档流程处理，不冒称程序又被重新构建。

可用的 `build/de-composition-20261019/apply_d.py` 默认只读检查，只有 `--apply` 才改正式树。它当前绑定上述 C commit/run、capture 与 D manifest，核对真实 acceptance、安装产物、配置保留和精确前像。使用顺序：

```powershell
Invoke-CheckedPython @('-B','build/de-composition-20261019/apply_d.py')
# 仅C全部出口通过、确认独占源码编辑后执行：
Invoke-CheckedPython @('-B','build/de-composition-20261019/apply_d.py','--apply')
```

缺少真实 acceptance 时应拒绝；不得手工伪造。若 C 实现再次修订，先冻结新的 capture、重新组合 D 和核对全部内容，再重建助手的约束；不能只改常量为当前HEAD。助手缺失时使用0.3节的逐文件受控应用流程。

**C 退出条件：** C1～C4、R1～R4、U1～U3适用项有实际证据；本轮正式发布成功、真实EXE查询/窗口/配置验证通过、旧新闻执行路径清退、未完成项明确；D只可从这个实际前像开始。

## 2. D：股东复杂样板实施

### D-01 明确修改范围与不变量

| 原正式模块 | 唯一目标模块 |
| --- | --- |
| `empire.contracts.holders` | `empire.features.holders.contract` |
| `empire.plugins.collectors.ths_holders_source` | `empire.features.holders.source` |
| `empire.plugins.collectors.ths_holders` | `empire.features.holders.collector` |
| `empire.plugins.datasets.holders` | `empire.features.holders.dataset` |
| `empire.plugins.data.holders` | `empire.features.holders.query` |
| `empire.plugins.data.holders_audit` | `empire.features.holders.audit` |
| `empire.plugins.ui.holders` | `empire.features.holders.ui` |
| `empire.plugins.collectors.holder_html` | `empire.sources.html` |

旧八模块全部调用方同批迁移并退役，不保留转发。共享 HTML 先归公共 `sources/html.py`，资本运作继续复用它，不允许资本运作反向依赖股东source/collector。

必须保持一个采集任务、一次必要 HTML 响应处理三栏、三个独立查询和三个独立页面。消息schema 5、SQL proof contract 4、preparation cache_revision 4、`response_group='holders.reports'` 保持。插件槽位 query 100/200/300、collector 400、UI 800/900/1000；任务300、数据贡献400；资本运作500/600/700原位。顺序必须比较完整身份序列，不能只数插件。

### D-02 按顺序合入候选

依次执行，完成前一步的冲突核对后才进行下一步：

1. **D-only 迁移。** 以实际 C 前像组合 D 路径/导入/白名单/bundle/coverage/rules/架构登记。原 D 草稿不能覆盖 C 最后修复。需要重建时读取 `compose.py --base c-81e147f --stage d` 与 `audit.py --stage d` 的当前源码和清单；如果实际C已变，先建立对应新capture，不继续使用旧标签。
2. **D 私有验证工具最终版。** 应用 `holder-verifier-draft-20261019/tree` 中 `scripts/source_test_storage.py`、`scripts/source_verification.py`、新 `scripts/verify_ths_holders.py` 及两个测试。保留revision2的SQL反例、关闭失败持有guard/锁、恢复时配置摘要检查。此版取代D原本只改import的旧verifier；E财报companion尚不应用。`financial-verifier-draft-20261019` 与 `ths_statement_test_storage.py` 已被取代，不能复活。
3. **D 公开契约注解。** 对 `features/holders/contract.py` 按 `d-holder-types-20261019/static-proof.json` 精确合并。先补本轮前像清单；保留9个函数原表达式、异常、顺序与默认值，RawReport/RawGap仅是未验证输入边界。把该文件追加到既有strict mypy清单，不新增ignore。
4. **D 容量安全工具。** 应用 `capacity-safety-draft/tree/scripts/capacity_session.py`、`tree/tests/test_capacity_session.py`，然后 `d/tree/scripts/measure_holders.py` 和 `measure_ths_capital.py` 差异。D不应用E的preview工具或SQL元数据文件。两阶段manifest仅列应应用目标，不从目录通配复制。
5. **真实SQL正向smoke工具。** 新增 `d-sql-positive-smoke-20261019/tree/scripts/smoke_source_storage_sql.py`。它复用第2步PrivateStorage/verify/recover/finish；不放宽SQL语法、不另造清理系统，也不嵌进已有integration autouse fixture，避免两套全局Engine guard相互阻止。
6. **D 文档精确段落。** 应用 `d-holder-documentation-20261019/paragraph-edits.json`，逐段核对唯一旧文。该文件已包括安全verifier的D说明；不能再重复叠其 `documentation-edits.json` D项。若先前已应用，只有新段逐字节一致才可记为已完成；E财报段仍后续单独处理。
7. **最终共享合并。** `docs/architecture-contract.json`、`docs/assembly-migrations.json`、`docs/documentation-coverage.json`、`plugins/collection/rules.json`、中央白名单、测试和内置正文按键/职责合并。保留C数据集额外贡献反例、C文档可达性、装配顺序参数和原业务验证。

最终D差异只应包含本批实现及所需工具/文档/证据；不顺手应用E/F的整树、最小schema、旧F正文或完整pyproject副本。

### D-03 容量工具重测前的必须修订

安全候选已写但未运行，且还有下列绑定收口要求。先完成并重新生成前像/候选清单，然后才测：

- holders 的bindings使用实际测量权威：`features/holders/{contract,source,dataset,query,audit}.py`、`sources/html.py`、`scripts/measure_holders.py`、`scripts/capacity_session.py`、`tests/test_ths_holders.py`。从机械整包清单移除不被测量执行的bundle/collector/ui及空 `__init__`，不是为了规避真正依赖变化。若实际查询新增其他依赖，明确补齐。
- THS-capital在D尚保留原业务路径，shared HTML改为 `sources/html.py`；保留实际contract/source/dataset/query/transport、measurement/helper/fixture等输入。不能提前绑定尚未加入D的 `sql/business-schema.json`。
- E采用外部表权威后，E的preview和THS-capital必须额外绑定 `src/empire/contracts/business_schema.py` 与 `sql/business-schema.json`；具体阶段见 [E实施](e-implementation.md)。preview固定合成 `version_observed_at=2026-10-11` 可保持，但conditions必须标注为**固定fixture版本日期**，报告执行日期使用本轮真实值。
- 实际server_uuid隔离、同连接锁归属、业务checkout身份、逐项清理、失败保留、报告先落盘再PASS必须通过反例。现helper不是通用SQL语法解析器；不要把checkout身份宣称为能检查任意跨库语句。
- 保持原合成规模、查询协议和阈值：holders 2500主体×4期；THS-capital 700证券。不得因新安全检查有成本而放宽阈值或减少规模。

旧active容量报告在D有两份失效：`holders.reports` 的 `ths-holders-run-outcome-capacity-2026-10-18.json`，以及 `ths.capital.security` 的 `ths-capital-followup-capacity-2026-10-18.json`。必须新测；不能只更新旧报告hash。设计卡只在新报告实际通过后改引用。

### D-04 静态、来源与安全工具测试

```powershell
Invoke-CheckedPython @('scripts/verify_release_environment.py')
Invoke-CheckedPython @('scripts/architecture_contract.py','check','--output',"build/$stageTag-architecture.json")
Invoke-CheckedPython @('scripts/assembly_contract.py','check','--baseline','docs/evidence/assembly-baseline-2026-10-19.json','--mapping','docs/assembly-migrations.json','--order-baseline','docs/evidence/assembly-order-baseline-2026-10-19.json')
Invoke-CheckedPython @('-m','ruff','check','src','tests','scripts')
Invoke-CheckedPython @('-m','mypy')
Invoke-CheckedPython @('-m','pytest','-q','--tb=short','-rs','tests/test_ths_holders.py','tests/test_holder_combined.py','tests/test_holder_error_shapes.py','tests/test_holder_identity_gaps.py','tests/test_holder_quality.py','tests/test_holder_ui.py','tests/test_holder_feature_lifecycle.py','tests/test_ths_capital.py','tests/test_source_verification.py','tests/test_verify_ths_holders.py','tests/test_capacity_session.py','--basetemp',"build/pytest-$stageTag-unit",'--junitxml',"build/$stageTag-unit.xml")
Invoke-CheckedPython @('-m','pytest','-q','--tb=short','-rs','tests/test_feature_bundles.py','tests/test_assembly_contract.py','tests/test_assembly_order.py','tests/test_assembly_source_gate.py','tests/test_architecture_contract.py','tests/test_ui_architecture.py','tests/test_ui_architecture_counterexamples.py','tests/test_preparation.py','tests/test_preparation_directory.py','tests/test_project_diagnostics.py','tests/test_documentation_sources.py','tests/test_architecture_benchmark.py','--basetemp',"build/pytest-$stageTag-boundaries",'--junitxml',"build/$stageTag-boundaries.xml")
```

必测业务反例：一次HTML三栏；排名并列/缺口；超十人完整名单与变动公告；空栏和未证明不同；未知值不填零；空名债券与同日具名债券不混并；报告期/窗口修订；部分证券失败继续并下轮从缺口恢复；嵌套HTML保留外层行和后续表；三页独立启停且惰性创建。

必测工具反例：相同实例的不同主机别名；无效server_uuid；SQL多语句/跨库/隐藏CTE/UPDATE修饰/DELETE USING/括号表绕过；服务关闭失败不能释放唯一所有权；配置/源码漂移；cleanup-only不采集；未知CREATE结果不猜删；任何dispose/DROP失败仍尝试其余清理；原异常与取消保留；报告已有/并发目标不覆盖；flush失败无成功报告；缺样本不以0ms通过。手写SQL字符串测试不能替代下一步真正metadata执行。

用 `rg` 搜索当前执行代码中的旧八路径，迁移映射/历史evidence允许保留作为历史。若测试路径真的迁移，先核对映射并更新命令，不能因文件不存在就静默删掉相应用例。

### D-05 私有归档/恢复集成和独立SQL正向smoke

```powershell
$dPriorIntegration = $env:EMPIRE_INTEGRATION
$dPriorSchemaMode = $env:EMPIRE_TEST_SCHEMA_MODE
try {
    $env:EMPIRE_INTEGRATION = '1'
    $env:EMPIRE_TEST_SCHEMA_MODE = 'full'
    Invoke-CheckedPython @('-m','pytest','-q','--tb=short','-rs','tests/integration/test_holder_archive.py','tests/integration/test_holder_run_outcome.py','tests/integration/test_holder_source_migration.py','tests/integration/test_ths_capital_archive.py','tests/integration/test_prefetch_pipeline.py','--basetemp',"build/pytest-$stageTag-integration",'--junitxml',"build/$stageTag-integration.xml")
} finally {
    $env:EMPIRE_INTEGRATION = $dPriorIntegration
    $env:EMPIRE_TEST_SCHEMA_MODE = $dPriorSchemaMode
}
Invoke-CheckedPython @('scripts/smoke_source_storage_sql.py','--test-mysql-settings',$stageTestSettings,'--security','601139.SH','--output',"build/$stageTag-sql-smoke.json")
```

必须检查JUnit中适用integration真的执行，不能全skip也记通过。覆盖重复无DML、可信摘要无SQL、有效修订与迟到旧响应、旧字段修复、提交后Redis确认失败及安全重放、断点丢失、同数异集、成功/相同/旧版均清队、下一证券不等待前归档、三栏后续写失败整事务回滚、可选Redis回SQL。

smoke必须单独进程串行运行：真实初始化经过未放宽的PrivateStorage SQL guard；看到实际CREATE及SQLAlchemy SHOW FULL TABLES/SHOW CREATE TABLE；SettingsStore写/相同免写/更新；三栏初始与修订经Redis→统一归档→正式browse第二页/detail/audit/preparation，私有待归档0。报告应明确 `mode=sql_positive_smoke`、`source_requests=0`、`sample_30_applicable=false`；SQL SMOKE PASS不等于实采。核对source/配置不变、六项cleanup完成、SQL/Redis无本轮残留。

### D-06 实际容量与T3

所有本地测试/构建/实采停止，桌面正常关闭；两种容量测量与T3也彼此串行。使用新报告路径：

```powershell
Invoke-CheckedPython @('scripts/measure_holders.py','--test-settings',$stageTestSettings,'--report',"build/$stageTag-holders-capacity.json")
Invoke-CheckedPython @('scripts/measure_ths_capital.py','--test-settings',$stageTestSettings,'--report',"build/$stageTag-capital-capacity.json")
Invoke-CheckedPython @('scripts/architecture_benchmark.py','measure','--test-settings',$stageTestSettings,'--protocol','docs/evidence/architecture-performance-protocol-2026-10-19.json','--baseline','docs/evidence/architecture-performance-baseline-2026-10-19.json','--output',"build/$stageTag-performance.json")
```

逐报告核对实际日期、server/client port、MySQL版本、durability、准确bindings/DDL scopes、所有原limits、测量完整、cleanup和最终passed。通过后以新名保存到 `docs/evidence/architecture-d-<能力>-capacity-<实际日期>-<run>.json` 并更新对应设计卡；保持原失败报告和旧历史报告。若复制公开报告，逐字节核对且脱敏审阅，不改数值或日期。

T3使用原冻结protocol、baseline和三份harness（`architecture_benchmark.py`、`architecture_benchmark_data.py`、其已冻结release-lock依赖），条件和摘要必须匹配。每项median/p95 ≤ max(基线×1.25，基线+协议噪声底限)，冷/装配/查询/UI底限分别100/2/1/5ms。保留全部样本与正确性摘要；未通过则修复、缩减范围或同条件完整重测，不调阈值、不选最快样本。此证据不代表网站吞吐或真实可见桌面速度。

### D-07 适用来源验收与失败恢复

最终如果涉及解析、请求、执行装配、恢复或消息语义变化，或无法证明纯位置/导入等价，按实质修改执行随机30股准入。纯组织迁移也必须有逐项AST/规范输出/身份顺序/恢复等价及明确范围的正式E2E抽验；不因“移动文件”自动免验。源码身份与实际已归档覆盖分别报告。

```powershell
Invoke-CheckedPython @('scripts/verify_ths_holders.py','--test-mysql-settings',$stageTestSettings,'--random-count','30','--seed','20261019','--proxy-only','--timeout','1800','--output',"build/$stageTag-source.json")
```

seed在请求前登记，此示例可用于既定复核；新计划需预先确定并保留。固定反例必须包含300398.SZ和601515.SH，并追加本轮已知失败证券；不能替代30只随机、换样凑数或把直连回退当代理证据。核对池摘要/名单/来源键与三栏内容、共享代理实际请求、Redis、统一归档、SQL正式查询、本轮私有队列0。

已知空名债券可能导致链路核对成功但 `acceptance_complete=false`、CLI FAIL；保持这些结论。`pipeline_verified`、`sample_30_met`、固定反例通过、来源gap与用途可用性分别判断，不用expected-gap白名单改成PASS。有关实际来源完整性未通过不能标为已验收；若仅组织迁移可独立接受，必须在阶段记录逐条给出适用理由，并在完成状态保留来源限制。

故障留下已核实本轮资源时，只用共享恢复入口和新的报告路径：

```powershell
Invoke-CheckedPython @('scripts/verify_ths_holders.py','--test-mysql-settings',$stageTestSettings,'--cleanup-only','--run-state',"build/$stageTag-source.json.ownership.json",'--output',"build/$stageTag-source-cleanup.json")
# SQL smoke使用自己的原ownership记录，不能混用source运行的记录。
```

正常进程未退出、owner/server/锁不匹配时不得猜测删除。`.ownership.json`保留本地，不提交或公开。cleanup-only只证明清理，不能改写失败来源验收。根据生产错误记录修程序时，另按确切项目/错误ID记录修复、验证、精确清理；一次查看或一次成功不等于全部历史错误已修复。

### D-08 文档、发布和退出

源码、工具、类型、测试、bindings和实际证据最终稳定后，更新公开说明/内置主题/coverage/存储说明，实现状态只写真实结果。最后审阅：

```powershell
Invoke-CheckedPython @('scripts/documentation_contract.py','review','--note','D股东业务归位：一次HTML三栏、公开契约、共享HTML、独立页面及私有验证和来源缺口说明同步；实测事实见本轮证据')
Invoke-CheckedPython @('scripts/verify_documentation.py')
Invoke-CheckedPython @('scripts/verify_database_design.py')
Invoke-CheckedPython @('-m','pytest','-q','--tb=short','-rs','tests/test_documentation_contracts.py','tests/test_documentation_review.py','tests/test_documentation_sources.py','--basetemp',"build/pytest-$stageTag-docs",'--junitxml',"build/$stageTag-docs.xml")
.\verify-release.ps1
```

review要求未改变的关联消费者理由时逐项核实后用现有 `--unchanged`/`--unchanged-reason` 接口记录具体理由，不用统一泛泛说明。正式门禁必须全量。最后按C同等方法真实EXE/可见桌面验收三栏、任务、查询、配置与正常重开。

**D退出条件：** 八条迁移及退役、C新增反例保留、H1/H2、适用H3、R/U/C规则、strict契约、真实SQL smoke、两份新容量及T3、文档/发布/真实桌面全部对应证据；未适用项有理由，未通过项仍标未通过。把最终D源码作为E前像；不能从旧D-only目录覆盖新增安全工具、注解或新证据。

## 3. F：最终 E 之后的共享治理

### F-01 入口条件和顺序

先确认 [E实施](e-implementation.md) 各批真实退出，实际最终树已具备各业务包、公共契约、唯一SQL元数据和当前capacity报告。`shared-closure/tree`仅供闭合审阅，不能当作已发布E或一次性全量应用计划。

按以下顺序执行：最终E前像核对 → 三项metadata精确编辑 + 通用共享门禁（同组验证） → 公开API类型增量 → 从最终正文重提取单源帮助 → 影响报告 → M1业务定位演练 → 可选测试成本配对实验 → 文档最后审阅、完整门禁和真实桌面。某项需再改公共文件时先合并其最新前像，随后重跑真正受影响项。

### F-02 三项metadata与通用共享门禁

精确编辑 `docs/architecture-contract.json`，只修改以下记录，保留其他module_groups、公有符号、owner、feature布局和历史债务：

| 模块 | 最终owner / role | 依据 |
| --- | --- | --- |
| `empire.build_info` | application / api | 只读构建信息与身份校验；从原composition组单独分出，bootstrap/__main__继续装配 |
| `empire.plugins.ui.help_content` | ui_components / parser | Article模型、离线正文解析/搜索；无业务页面或服务 |
| `empire.plugins.ui.help_reader` | ui_components / shared_ui | 渲染调用方传入正文和Qt控件；不持业务状态 |

`plugins.ui.help`仍是help业务页面，help owner仍是business。不得把整个help业务改平台以消除依赖，也不能把kernel/infra改成application来规避门禁。

在最终 `scripts/architecture_contract.py` 上应用F规则：所有 `source owner.kind=platform → target owner.kind=business` 导入均拒绝，目标即使是公开contract/api/package或public_symbols也不例外。真实装配豁免仅application的composition/dataset_registry及diagnostics的composition；kernel/infra/pipeline/scheduler/shared_ui不能靠改role获得豁免。所有owner.kind均校验，未被模块使用的owner也不能写未知kind。shared_to_business不能通过旧debt豁免。

**必须替换E原窄分支，不可叠加：** 删除原按特定owner硬编码的shared_to_business及独立shared_ui_to_business分支，保留原跨业务私有、reader→execution、环路及其他规则。E已有反例改为统一规则名，composition正例owner应为真实application；kernel冒充composition/registry必须失败。将 `tests-additions.txt` 精确追加到当前 `tests/test_architecture_contract.py`，保留E已有 `test_shared_business_architecture.py` 并同步其断言，不能用旧整测试文件覆盖。

```powershell
Invoke-CheckedPython @('scripts/architecture_contract.py','check','--output',"build/$stageTag-shared-architecture.json")
Invoke-CheckedPython @('-m','pytest','-q','--tb=short','-rs','tests/test_architecture_contract.py','tests/test_shared_business_architecture.py','tests/test_ui_architecture.py','tests/test_ui_architecture_counterexamples.py','tests/test_assembly_contract.py','tests/test_assembly_order.py','--basetemp',"build/pytest-$stageTag-shared",'--junitxml',"build/$stageTag-shared.xml")
```

反例覆盖绝对/相对/别名/局部/TYPE_CHECKING/字面量动态导入、包再导出、公有符号、未知kind、未使用owner、debt逃逸、kernel装配伪装和合法application装配。非字面量反射不能被静态图证明安全，必须明确登记/审阅，不能据门禁通过宣称任意Python运行时隔离。

### F-03 公开契约的strict增量

按 `f-public-types-20261019/candidate.patch` 合并五个真实路径：

- `src/empire/features/stocks/api.py`：调用方Connection及DirectoryPayload，不重开事务。
- `src/empire/features/calendar/api.py`、`contract.py`：同连接366天读取、时间/日期/行字段和原失败理由。
- `src/empire/contracts/preparation.py`：公共CheckEvidence/findings及初始化注解。
- `src/empire/contracts/confirmation.py`：实际SQL/Redis服务结构协议与异构确认内容。

**公共preparation必须保留原路径。** `contracts/preparation.py`、`contracts/preparation_scope.py`是唯一公共协议；研究/聚合实现才在features/preparation。已撤销的 `features/preparation/contract.py` / scope候选不能重新加回来，不能加兼容转发。

保留三个有解释的Any别名：DirectoryPayload、RawCalendarRow、ConfirmationPayload；服务参数不再无区别Any。保留D的RawReport/RawGap边界。只在原strict清单追加缺失入口，同时保留已检查的holders contract和kaipanla API。不得添加ignore_errors、ignore_missing_imports、disable_error_code或follow_imports=skip来通过。

比较函数去参数/返回/局部类型注解后的AST，所有表达式、默认值、SQL、异常、分支不变；类型声明/import单列。随后实际运行mypy；静态等价并不证明mypy或注解反射完全不变。

```powershell
Invoke-CheckedPython @('-m','ruff','check','src','tests','scripts')
Invoke-CheckedPython @('-m','mypy')
Invoke-CheckedPython @('-m','pytest','-q','--tb=short','-rs','tests/test_foundation_public_api.py','tests/test_calendar_preparation.py','tests/test_preparation.py','tests/test_preparation_directory.py','tests/test_kaipanla_public_inputs.py','tests/test_ths_holders.py','--basetemp',"build/pytest-$stageTag-types",'--junitxml',"build/$stageTag-types.xml")
```

如果类型工具迫使业务算法改变，先缩小注解范围或独立设计该行为变化，不能把修算法混入“纯类型等价”。容量bindings包含改动文件时按实际失效范围真实重测；不能认为注解永远不影响字节绑定。

### F-04 从最终正文提取一份权威帮助内容

F旧稿的143主题/164目标只是旧捕获快照，不是当前必须凑出的数量。正式操作步骤：

1. 读取最终E `src/empire/plugins/ui/storage_reference.md`、coverage、README和各业务说明，保存其原始字节与主题顺序。核对新增/删除/重命名主题，先修订ownership映射；保留所有C/D/E实际正文和来源限制。
2. 从这份**尚未迁F的最终正文**提取完整主题到新建的本轮build目录，不从F旧tree复制文章。每个完整主题按最终业务职责归 `features/<业务>/docs/help/`；跨业务规则归 `src/empire/documentation/topics/`。不按字数或网站机械切块。
3. 若准备工具存在，使用其拒绝覆盖的入口；目标必须尚不存在：

```powershell
Invoke-CheckedPython @('build/f-docs-preparation-20261019/extract_sources.py','--root','D:\project\empire','--destination',"D:\project\empire\build\$stageTag-help-extraction",'--ownership','build/f-docs-preparation-20261019/ownership.json')
```

4. 提取器缺失时按 `<!-- topic:分组|标题 -->` 完整边界重建stdlib提取器：先验证主题唯一、集合与owner映射相等、规范仓库路径且无越界，再写**新**build目录和提取清单；任何集合错误不写半份正式输出。它仅用于一次准备，不装入运行时，不承担旧格式回退。
5. 保留提取后的每个完整主题，在“文档分工与更新”等适用主题追加真实维护流程。`help-index.json`只登记owner/path/顺序，不复制标题/正文；核对文件集合精确相等。主题元信息仍来自正文，coverage继续拥有page/task/table/key关联。
6. 合并正式编译器 `scripts/documentation_build.py`、parse_articles纯文本入口、review schema3、release check与包资源核对、全部反例。现有 `read_articles`/`articles` API和源码/frozen资源路径不变。现 `storage_reference.md`作为受Git跟踪的**生成聚合物**保留，禁止手工编辑；运行时不生成、不搜索旧正文回退。
7. `.gitattributes`只为片段/清单/聚合物固定LF，并纳入发布和preparation源摘要；不全仓改换行。Empire.spec继续打包已检查聚合物，保留E财报资源等所有后续修改。
8. 在冻结前显式generate；发布门禁内只check，不允许release过程写回冻结src。check输出的help-report、每源摘要/顺序/聚合摘要绑定同轮inputs，打包后资源字节再与已检查聚合物比对。

合并共享 `documentation_contract.py` 时必须同时保留C源码可达性、E `business-schema.json` 资源可达绑定、每表PK/来源/required_columns/维护位置及primary-key exemption信息、当前review失效机制。旧F整文件不含所有这些后续改动，禁止覆盖。

```powershell
Invoke-CheckedPython @('scripts/documentation_build.py','generate')
Invoke-CheckedPython @('scripts/documentation_build.py','check','--report',"$stageTag-help-check.json")
Invoke-CheckedPython @('-m','pytest','-q','--tb=short','-rs','tests/test_documentation_build.py','tests/test_documentation_review.py','tests/test_documentation_sources.py','tests/test_documentation_contracts.py','tests/test_storage_help.py','tests/test_rule_documents.py','tests/test_release_steps.py','tests/test_packaged_runtime.py','tests/test_release_pipeline.py','--basetemp',"build/pytest-$stageTag-help",'--junitxml',"build/$stageTag-help.xml")
```

当前候选的 `--report` 相对 `root/build` 解析，因此传文件名即可；重基后先读真实CLI，不能误写 `build/build/...`。测试必须覆盖：两次生成字节相同且无变化不刷新mtime；不同cwd相同；建立文件顺序不影响主题顺序；嵌套孤立片段、大小写/扩展名、重复/缺失主题或路径、越界和symlink、无效help链接、手改/过期聚合均拒绝；只改片段未generate时review拒绝；正文不变但owner/path迁移也令review过期；校验失败不改输入；source/模拟包Article全字段和顺序一致；真正frozen资源缺失/改变阻止发布且不回退。

最终再人工核对用户操作说明入口、保存/生效、结果、限制和故障处理。编译与链接检查不等于正文语义正确。

### F-05 影响报告与M1三个定位演练

集成 `scripts/change_impact.py`、`tests/test_change_impact.py`，基于真实architecture/assembly/preparation声明与静态反向依赖，不复制第二登记表。脚本和测试仅AST读取，声明构造不启动服务。公共/未知/删除/非Python资源/动态依赖不明/元数据错误扩大为全量；conftest扩大到所在子树，测试fixture消费者也进入闭包。

```powershell
Invoke-CheckedPython @('-m','pytest','-q','--tb=short','-rs','tests/test_change_impact.py','--basetemp',"build/pytest-$stageTag-impact",'--junitxml',"build/$stageTag-impact.xml")
Invoke-CheckedPython @('scripts/change_impact.py','--changed','src/empire/features/news/ui.py','--output',"build/$stageTag-impact-news.json")
Invoke-CheckedPython @('scripts/change_impact.py','--changed','src/empire/features/holders/source.py','--output',"build/$stageTag-impact-holders.json")
Invoke-CheckedPython @('scripts/change_impact.py','--changed','src/empire/contracts/task.py','--output',"build/$stageTag-impact-public.json")
```

逐项核对选中测试和真实调用方，不要求选择数量越少越好。报告所有测试/来源/桌面初始仍未完成；历史实采引用仅 historical_reference_only，不能变成当前源码通过证据。执行选择性测试只缩短反馈，正式发布仍全量。

确保每个最终业务包有唯一README定位入口：公开契约、关键文件、数据归属、生命周期、专项测试和权威说明。使用 `e-readme-locality-draft` 的追加hunk时保留实际D的holders说明、E的stocks确认职责、data_browser公共UI归位和preparation公共契约。没有草稿则按这六项从实际声明/文档/测试重建，不编造查询能力或数据表。

在私有源码副本做三个M1演练，不能把演练代码留在正式src：

1. 页面文案：仅修改新闻页面placeholder，实际离屏构造原Page验证文案和只读详情；本项不是可见桌面验收。
2. 来源字段：复用当前 `tests/test_sina_news.py` 的 `raw_row` 与 `test_plain_text_with_ampersand_is_flushed_before_empty_validation` 原函数。移除parser.close复现H&M尾部丢失，失败必须定位该历史函数且以AssertionError结束；ImportError、非零退出本身不算成功复现。恢复原源码后同一原断言通过。
3. 独立业务：在副本新增仅声明bundle，中央 `FACTORIES` 仅加一项；完整原插件/task/dataset字段和既有相对顺序保留。声明期间socket/file/read_text/read_bytes/manager.start/autostart/QWidget创建均有禁止哨兵；不启动采集、入队或数据库。

**副本必须复制受Git跟踪的 `sql/` 资源，包括 `sql/business-schema.json`。** E之后公开存储权威会在导入时读取该资源；只复制src会出现假ImportError。不得复制config.toml、私有MySQL目录、ownership恢复凭据或数据库业务文件。正式源输入在演练前后及finally逐文件核对，失败也落盘且源变化必令passed=false。

```powershell
# 先读当前run.py和检查器；它默认不执行，以下仅在最终F环境解冻后运行。
Invoke-CheckedPython @('build/m1-locality-drills-20261019/run.py','--execute')
```

工具缺失则按上述三项重建副本演练；只记录实际改动范围和结果，不凭文件数/token理论声称AI效率提高。若根因本来属于公共契约，应修唯一共享路径并扩大回归，不能复制本业务补丁来凑M1局部性。

### F-06 可选的测试初始化成本实验

本项是**先实测后决定是否采纳**。已有C成本背景为56例setup/teardown占比较高，但未拆create_db/DDL/drop；它不是下面六例full/minimal配对基线，也不能证明最小schema一定有收益。

原预登记协议为 `build/f-test-cost-preparation-20261019/protocol.json`，SHA `311e16ae019bddd2f7e58cce20def5126487eda109a30e024364ea8059fcf308`。六例固定如下，精确collect确认存在，不换样：

```text
tests/integration/test_news_archive.py::test_fingerprint_hit_skips_sql_and_miss_confirms_then_deletes_queue
tests/integration/test_news_archive.py::test_fingerprint_cache_failure_after_commit_preserves_queue
tests/integration/test_holder_archive.py::test_hot_cold_revision_old_observation_and_field_repair[top_holders]
tests/integration/test_holder_archive.py::test_sql_commit_ack_failure_replay_and_checkpoint_loss[top_holders]
tests/integration/test_rule_archive.py::test_hot_cold_zero_dml_metadata_revision_late_old_and_corruption[limit_rules]
tests/integration/test_rule_archive.py::test_sql_commit_ack_failure_recovers_without_redownload[limit_rules]
```

若候选存在，先对最终E/F做**语义重审**，再生成新的审阅绑定：真实fixture、requires/provider、dataset/schema/project、startup/query/archive/setup/teardown及外键都核实。旧profile绑定C文件，运行应回full；禁止只刷新hash强行恢复minimal。

| 用例组 | 最少完整表组与原因 |
| --- | --- |
| 新闻 | stock、collection_state、finance_news、app_setting；包括fixture teardown DELETE stock与MySQL core要求 |
| 股东 | stock、collection_state、app_setting、holder_report、holder_member；保留三栏语义与FK |
| 规则 | collection_state、app_setting、trading_rule_citation、trading_rule_value；保留引用与修订 |

正式候选必须保持每例UUID数据库/Redis namespace、全Engine归属guard、原全部业务断言和销毁；默认full调用原initialize_database。minimal仅六个精确nodeid，从唯一sql/schema.sql选完整原DDL，保留字段/索引/CHECK/FK/引擎/顺序。未知节点、源码/文件集合/依赖变化或不支持DDL，在任何DDL前回full并说明原因；一旦开始执行DDL，失败直接失败，不能捕获缺表再补建或重跑。迁移/schema/shape/index用例继续full。

先运行新负例 `test_schema_ddl.py`、`test_schema_fixture.py`、`test_schema_ownership.py`，覆盖跨库/未知语法/FK闭包/字符串伪REFERENCES、参数化ID、声明变动、配置别名/任意Engine误连、DDL/call失败清理及listener移除。完整发布检查仍保留，不得因为本实验删测试。

确认无并发负载、桌面关闭、实际独立13348及冻结依赖后，加载已审阅protocol的nodeids。以下仅示范一次collect及单批；按协议执行1次预热和4组交替，每批必须新pytest进程：`full,minimal`、`minimal,full`、`full,minimal`、`minimal,full`。

```powershell
$fProtocol = Get-Content -Raw -LiteralPath 'build/f-test-cost-preparation-20261019/protocol.json' | ConvertFrom-Json
$fNodes = @($fProtocol.nodeids)
Invoke-CheckedPython (@('-m','pytest','--collect-only','-q') + $fNodes)

$fPriorPythonPath = $env:PYTHONPATH
$fPriorIntegration = $env:EMPIRE_INTEGRATION
$fPriorMode = $env:EMPIRE_TEST_SCHEMA_MODE
$fPriorReport = $env:EMPIRE_SCHEMA_REPORT
try {
    $env:EMPIRE_INTEGRATION = '1'
    $env:PYTHONPATH = (Resolve-Path -LiteralPath 'build/f-test-cost-preparation-20261019').Path
    $env:EMPIRE_TEST_SCHEMA_MODE = 'full'
    $env:EMPIRE_SCHEMA_REPORT = "build/$stageTag-pair01-full.json"
    # 下一批单独进程改为minimal及新报告/basetemp；不得重复覆盖pair01。
    Invoke-CheckedPython (@('-m','pytest','-p','schema_phase_observer','-q','--tb=short','-rs','--basetemp',"build/pytest-$stageTag-pair01-full") + $fNodes)
} finally {
    $env:PYTHONPATH = $fPriorPythonPath
    $env:EMPIRE_INTEGRATION = $fPriorIntegration
    $env:EMPIRE_TEST_SCHEMA_MODE = $fPriorMode
    $env:EMPIRE_SCHEMA_REPORT = $fPriorReport
}
```

observer只计时不选例；记录collection、setup/call/teardown、plan/create_db/ddl/drop_db和每例实际schema_mode、outcome、skip reason。minimal回退full的批次不是有效候选样本。六例的nodeid/outcome/skip必须一致，无新增skip。plan成本计入setup和total，不能扣掉它改善比例。

采纳阈值固定：setup合计中位数比≤0.7，total合计中位数比≤0.8，每例call p95≤max(full×1.25,full+0.050秒)，所有正确性/归属/完整门禁仍通过。**没有收益就不落地fixture优化**，保留原full初始化和真实实验结论；F可通过影响报告改善反馈，不要求为了交付强行采用minimal。协议/原始样本缺失时按0.3节先预登记重建，不能事后调阈值。

### F-07 最终文档、门禁、真实桌面与交付

最后一次实现/片段/清单/资源/测试修改后先generate，再人工审阅操作语义，然后执行review/check和正式全量门禁。门禁内不得generate或手改review摘要。F源码、正式报告、帮助资源、包产物应关联同一轮身份。

```powershell
Invoke-CheckedPython @('scripts/documentation_build.py','generate')
Invoke-CheckedPython @('scripts/documentation_contract.py','review','--note','F最终审阅：权威帮助片段及离线聚合、共享边界归属与统一门禁、公开契约类型、影响报告和经实测决定的测试成本方案同步')
Invoke-CheckedPython @('scripts/verify_documentation.py')
Invoke-CheckedPython @('scripts/verify_database_design.py')
Invoke-CheckedPython @('scripts/architecture_contract.py','check','--output',"build/$stageTag-final-architecture.json")
Invoke-CheckedPython @('-m','mypy')
.\verify-release.ps1
```

真实正式EXE核对帮助搜索、章节、help链接、阅读历史、按需创建、不同cwd、构建身份、数据库只读查询与正常关闭/重开。包中聚合物与本轮check摘要一致；缺失/改变不能切换正式发布。离屏绘制、模拟包布局和M1不能代替真实窗口。

交付逐项填写：实际修改/退役；最终源码与manifest；静态/专项/集成/T3/容量/适用实采；M1/M2/M3/T1/T2/T3；文档review和完整release；配置/资源保留；真实桌面；实验是否采纳及原因；全部未完成项。严格类型仅报告具体覆盖文件，选择性影响报告仅报告反馈范围，不能宣称全项目类型安全、运行时沙箱或未测得的性能提升。

**F退出条件：** 一份权威正文、确定性聚合及真实包资源一致；共享边界通用门禁无债务豁免且反例通过；公共契约唯一原路径与strict实测通过；完整定位入口和三个演练有真实证据；影响报告保守且不取代全量；测试成本优化仅在收益/正确性都达标时采用；文档、正式发布和真实桌面全部闭环。
