# E 阶段：按业务包逐批迁移的实施手册

本手册是**待执行方案**，不代表 E 已应用、测试通过或已发布。当前完成范围以[当前事实](status.md)为准；总路线见[总入口](README.md)，D/F 见[C/D/F 手册](cdf-implementation.md)，证据定义与统一退出标准见[验收手册](acceptance.md)。本手册、[迁移清单](planned-migrations.json)与仓库正式源文件共同构成可重建输入；不得依赖某台机器的 ignored `build` 草稿才能实施。

## 1. 目标、前置项与不可变边界

E 的目标是让来源解析、业务契约、数据归档、正式查询、数据准备和业务页面能够在相邻的 `features/<业务>/` 内定位。FeatureBundle 是代码归属与声明的组合单位；PluginManager 中原有运行插件仍保留原身份、依赖、顺序、启停与偏好。不要把每个函数改成可热插拔对象，也不引入第二个注册器。

开始 E0 前必须同时满足：

- [ ] C 已完成真实发布及发布后可见桌面验收；D 已完成自己的实施、容量复测、发布和发布后验收。仅测试通过或仅存在 EXE 不足以进入下一批。
- [ ] 读取实际前一批提交、发布清单、未完成项及失败记录；确认主任务没有运行正式门禁、打包、实采或其他源码编辑者。
- [ ] 读取 `AGENTS.md`、[开发流程](../development-workflow.md)、[采集指南](../collector-development-guide.md)、[说明维护](../documentation-maintenance.md)和本批业务文档。存在新要求时按当前正式要求更新本批任务卡。
- [ ] 核实工作区已有改动、运行中的 Empire、端口/私有测试库归属、共享 Redis 待归档状态及配置实际位置。不得输出密码，不能清空共享 Redis、修改 RouterProxy 目录或重启数据库来制造干净环境。
- [ ] 保留 D 已交付的类型、公共 HTML、安全验证辅助、容量安全辅助、新增测试/说明/证据；E 从**实际验收后的 D**继续，不能用 C 时期候选树覆盖 D。

本阶段保持唯一正式路径：共享下载/代理/频控、共享预取及资源预算、统一入队、统一归档/摘要、调度、SQLLane、QueryScope、PageContribution、单实例与发布流程不另造实现。无目录扫描、运行时动态发现、转发兼容模块、重复注册、双写、启动 DDL 或隐式迁移。正常请求次数与集合校验语义不因搬家改变。

每个 E 子批单独完成本手册第 2 节，发布验收后才进入下一批。E6b 可以进一步拆为三个独立批。全量闭合树只能用于审阅终态依赖，不能一次性应用整个 E。常规实施和验证在既有授权内自主完成；本手册不增加逐步确认。

## 2. 每个批次必须执行的完整循环

### 2.1 建立本批可审阅输入

1. 记录 `git rev-parse HEAD`、`git status --short`、当前发布 run、前一批真实验收记录；为本批分配唯一 run ID。创建 `build/architecture-<阶段>-<run>/` 存本轮临时输出，正式成功证据另归档到新的 `docs/evidence/` 文件。
2. 按 `planned-migrations.json` 的 `phase` 筛选本批 `modules`、`symbols`、`path_splits`、`authority_changes` 和 `new_target_files`。该 JSON 的 hash 是**审阅时前像/候选身份**，不是未来已验收源码必须恢复到的字节；它不是可直接传给 `assembly_contract.py --mapping` 的运行迁移文件。
3. 从实际前批读取每个旧路径，记录本次旧字节 SHA-256、目标是否存在、目标现有 hash、写入/退役理由。先验证所有路径都位于项目根内；每个源定义只认一个权威。遇到前像变化先审差异，保留新的业务修复与证据，不能只更新一个常量 hash 跳过差异。
4. 构造当前批的精确改动表：旧入口→新入口、符号拆分、所有调用方/测试字符串/monkeypatch 目标/打包资源/文档覆盖/设计卡、要删除的旧文件。`path_splits` 比单一模块映射更细；一个旧文件拆成多职责时必须逐符号迁移。
5. 审阅“纯搬移”与“行为/装配改变”两类差异。纯搬移至少提供去除导入位置和必要名称变化后的 AST 对比、函数签名/数据结构/异常/持久化字段和调用参数比较；发现解析、分支、恢复、请求顺序、消息或默认值变化即列为实质修改，不靠目录重构名义豁免。

如果 ignored 草稿已经丢失：按旧源文件和本清单重建目标包，逐定义搬移，再按本手册明确的共享边界调整。不要新建名字相同的空函数来满足导入；不要依赖 `compose.py`、`apply_d.py` 或历史 build 工具存在。可以为当前批制作新的标准库精确前像应用器，但其读写边界、冲突拒绝与恢复须先审阅；没有现成通用 E 自动应用器。全部原行为必须从正式前批源读取。

### 2.2 实施时的固定顺序

1. 新建本批包与 `README.md`，先放纯契约/公共 API，再放来源解析、执行、dataset、query/audit、UI。文件按职责拆分，禁止靠压行满足上限。
2. 原值复制 contribution：插件 ID、depends、任务 ID、dataset namespace/job→project、schema version、归档模式、stale outcome、页面 ID/分类/顺序/缓存策略和原显式槽位。顺序以原声明为准，不能把现有槽位重新连续编号。
3. 从 `features/remaining.py` **仅移走本批声明**；在 `features/builtin.py` 显式加入本批 bundle。数据准备后置装配仍等完整业务列表准备好再构造，不扫描包目录。未迁移贡献继续由 remaining 持有。
4. 更新所有生产导入、类型引用、静态路径字符串、测试 patch 路径、脚本、包资源、coverage、架构 ownership 与正式 `docs/assembly-migrations.json`。形式相同但业务含义不同的字段不可机械替换。
5. 删除本批已替代旧实现，检索旧路径残留。历史证据里的原路径/hash保持不变；当前说明、当前声明、正式调用与可执行测试不得再使用退役入口。不要保留 forwarding 模块让两条路径长期共存。
6. 在本批 README 写清“改来源/改字段/改归档/改查询/改页面/查验证”分别从哪里进入，并记录公开依赖、生命周期、数据限制及专项测试；公共工具仍链接其真正公共归属，不复制到本包。
7. 对照实际旧代码复核请求次数、入队与归档解耦、断点及成功清队。取消后所有预取请求/额度回收；成功SQL、相同内容、可信摘要命中和过时版本都按统一归档器删除对应消息，失败保留。

### 2.3 本批本地命令和证据

以下 PowerShell 变量由执行者在项目根设置为**本轮真实路径**。`$testSettings` 必须是已核实独立 MySQL 13348 的配置 JSON；先验证实际 `server_uuid`/datadir 与正式实例不同，不能只凭端口值。不得将凭据写入提交或输出。使用项目 `.venv`，不要混用系统 Python。

```powershell
$run = '<阶段>-<唯一运行ID>'
$out = "build/architecture-$run"
$py = '.\.venv\Scripts\python.exe'
$testSettings = '<已核实的独立MySQL13348配置JSON绝对路径>'
New-Item -ItemType Directory -Path $out -Force | Out-Null
& $py scripts/architecture_contract.py check --output "$out/architecture.json"
& $py scripts/assembly_contract.py snapshot --output "$out/assembly.json"
& $py scripts/assembly_contract.py check --baseline docs/evidence/assembly-baseline-2026-10-19.json --mapping docs/assembly-migrations.json --order-baseline docs/evidence/assembly-order-baseline-2026-10-19.json
& $py -m pytest tests/test_assembly_contract.py tests/test_assembly_order.py tests/test_assembly_source_gate.py tests/test_architecture_contract.py tests/test_ui_architecture.py tests/test_ui_architecture_counterexamples.py --basetemp "build/pytest-$run-common" -q
```

逐命令检查退出码，失败立即保留输出并修复，不能把一串命令最后返回 0 当作全部成功。这里的 snapshot 会导入正式装配声明但不启动插件；不得在他人冻结门禁时执行。`ui_architecture_contract.py` 没有独立 `check` CLI，使用其专项测试和正式门禁，不编造命令。

各阶段下列 pytest 列表是起点，不替代精确变更影响分析。测试文件没有原地改名时沿用原文件名；增加的反例不得只重复实现。集成测试须显式启用并使用独立实例，不能将 skip 当通过：

```powershell
$previousIntegration = $env:EMPIRE_INTEGRATION
$previousTestSettings = $env:EMPIRE_TEST_MYSQL_SETTINGS
try {
    $env:EMPIRE_INTEGRATION = '1'
    $env:EMPIRE_TEST_MYSQL_SETTINGS = $testSettings
    # 此处执行本阶段列出的 tests/integration 路径，指定唯一 --basetemp。
} finally {
    $env:EMPIRE_INTEGRATION = $previousIntegration
    $env:EMPIRE_TEST_MYSQL_SETTINGS = $previousTestSettings
}
```

现有集成 fixture 创建 UUID 私有 schema 和 namespace；这不替代执行前实例归属核实，也不证明任何新临时工具已安全。真实请求统一走共享代理设施；开发观测 `use_proxy=true/proxy_fallback=true`，回退按现有共享限制。宣称适用“随机30股代理实采”时，必须使用适用池随机抽取至少30只不同股票、记录池/种子/名单，固定失败证券额外加入，实际请求全部代理，来源→规范化→Redis→统一归档→正式查询逐股票/日期/业务键核对内容，全部成功且本轮 pending=0。回退只能算开发观测，不能替代严格代理准入；不能换掉失败股票。不按股票采集、适用池不足30或纯组织迁移豁免必须逐项说明依据，不能统一写“不适用”。

### 2.4 容量、性能、说明和发布

最后一次实现/类型/工具/fixture修改后，扫描当前设计卡所有 `capacity.status=measured` 的绑定；任何实际被修改的绑定都必须重测，不能仅按后面预测清单判断。历史 JSON 不改、旧 hash 不刷新，失败报告不删除，新报告使用新路径；成功报告必须记录真实时间/环境/范围/输入 hash/全部原阈值/清理结果。

所有可写容量工具先审查：实际实例身份、独占UUID schema和owner/锁、每次会话真实数据库、精确Redis namespace、成功创建才有删除权、独立清理与取消保护、报告禁止覆盖、清理失败不能输出PASS。D的 `scripts/capacity_session.py` 与 `scripts/source_test_storage.py`/`source_verification.py` 是共享入口；后续工具适配其契约，不再造一套删除逻辑。旧脚本存在不表示已满足这些要求。

```powershell
& $py scripts/verify_database_design.py
& $py scripts/architecture_benchmark.py measure --test-settings $testSettings --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output "$out/performance.json"
& $py scripts/architecture_benchmark.py compare --report "$out/performance.json" --baseline docs/evidence/architecture-performance-baseline-2026-10-19.json --output "$out/performance-comparison.json"
& $py scripts/documentation_contract.py review --note '<本批修改、同步正文和已审阅行为的具体说明>'
& $py scripts/documentation_contract.py check
```

T3 仍使用已登记协议和原阈值，每项 median/p95 ≤ max(基线×1.25，基线+该类噪声底限)；不能测后改预算、挑快样本或把离屏结果写成真实桌面。基准工具实际绑定 news/holders 等代表负载；它不替代本批业务容量。本轮禁止修改冻结T3 harness、协议、历史基线、阈值及 `scripts/release_lock.py`。现行harness通过provider查询业务，不需要为普通业务模块搬家修改。发现不兼容时保留失败记录，先核实本批公开路径和装配是否错误；确需工具修复须拆成独立审阅范围，重新明确可比协议和证据要求，不能在E中适配后沿旧baseline强行比较。运行时正常关闭桌面并独占发布/测量环境。

说明审阅必须在最后一次实现修改之后；之后再改源码/正文，旧审阅无效。同步程序内主题、页面 coverage、结构/存储正文、业务 README和当前证据引用；纯内部变化确实无用户行为影响才以具体 `--unchanged-reason` 说明，不能仅刷新摘要。执行相关文档/领域回归后按[开发流程](../development-workflow.md)完成提交、main合并/推送和唯一正式发布入口：

```powershell
.\verify-release.ps1
```

脚本内部调用统一 `scripts/release.py`，不要自造打包入口、伪造 receipt 或绕过失败。恢复仅按正式流程使用 `-Recover`，不重写失败记录。发布后实际启动发布 EXE，保持其同目录已有 `config.toml`，在不同工作目录启动，检查真实 MySQL/Redis连接、受影响正式查询及可见页面、插件启停、未保存编辑与导航。原配置 hash 前后相同；不要把含凭据程序目录作为公共资源上传。详单见验收手册。

### 2.5 批次完成条件和失败恢复

每批至少保存：前批提交/发布与本批差异清单；精确装配身份和顺序比对；旧路径清退/所有权/依赖图；语义反例/恢复测试/适用实采记录；正式查询集合/内容与本轮待归档0；容量绑定失效清单及真实新报告；T3；说明审阅及门禁；本批提交/远程HEAD/发布run/源码与EXE身份；可见桌面、不同工作目录与配置保留记录；未覆盖范围。

- [ ] 全部适用项有本轮证据且 pass；未实施、未测和不适用分别写明，不能填默认0或“同上”。
- [ ] 失败例不能被成功例抵消；本轮源码变动后的旧证据不再充当最终证据。
- [ ] 更新 `status.md` 和本批正式记录后，下一批才可开始。不能只勾文档表格而没有发布验收链接。

失败时先停止推进、保存诊断和精确ownership记录。源码冲突只回退本批仍保持候选字节的文件，保护其他人的修改；不使用 `git reset --hard` 清场。未改变持久化契约时按正式发布恢复上一验收代码包，保留配置/业务数据/队列；若发现 schema、消息或断点契约其实改变，必须按其专门迁移/恢复方案处理，不能旧EXE硬回退。不删除未知业务消息来消除错误。不强杀数据库、删锁或无条件清错误列表；错误修复只清本次已登记且已验证的确切ID。

## 3. E0：SQL 归属资源与共享边界准备

**输入**：D完整验收；正式 `contracts/business_schema.py` 以及它引用的 KPL/THS 资本常量、`sql/schema.sql`、`sql/schema-contract.json`、数据库设计卡和打包声明。此批不迁移业务表。

**实施顺序**：

1. 把旧代码计算出的业务归属逐项转成 `sql/business-schema.json`，明确 `schema/fixed_sources/tables/dataset_tables/dataset_table_groups/primary_keys/source_overrides/required_columns/primary_key_exemptions`。旧值、顺序、主表/子表关系全部保存。
2. `contracts/business_schema.py` 变成读取该唯一资源的通用校验器与原公共API；不再导入 KPL 或 THS 资本。保留 `FIXED_SOURCES` 的MappingProxyType、`TABLES`的tuple、`DATASET_TABLES`的dict、`DATASET_TABLE_GROUPS`值为tuple、`PRIMARY_KEYS`值为list。新增 `read_business_schema(path)`、`dataset_tables(dataset)`，错误明确失败，无旧常量回退。
3. 对比五组旧映射：51项固定来源、54项维护TABLES、49项dataset主表、49项表组、52项主键；这些数字只作辅助，必须比较**每项值、类型和顺序**。实际SQL有55表，`suspension_source_date`不在旧TABLES/fixed sources但在表组/主键，不能为凑全表而改变维护清单。
4. 显式保留stock双源`sina/ths`、新闻不套固定来源限制、资本行为必需`unified_code`、finance_news/collection_state/app_setting主键例外及原schema_contract输出形状。
5. `Empire.spec`打包资源；数据库设计门禁用显式root核对当前DDL/正式数据贡献/主键/必需列；说明源追踪与表文档摘要包含此JSON。资源缺失、重复JSON字段、非法标识/版本/未知表/错误主键等必须拒绝。
6. E0先建立资源与通用读取器。KPL/THS资本的业务侧采用放到E4/E6a，避免来回改容量绑定；若选择提前接入，必须把其容量失效和复测纳入E0，不得遗漏。

**验证起点**：既有 `tests/test_business_schema_contract.py`、新增 `tests/test_business_schema_metadata.py`、`tests/test_documentation_sources.py`、数据库设计/装配公共测试；按需独立库验证 `tests/integration/test_business_schema_migration.py`，但不在正式库执行结构迁移。新增反例覆盖资源丢失/重复字段、表组顺序错、遗漏子表主键、来源例外不含正式来源、必需字段无主键、错误root和旧source列。

```powershell
& $py -m pytest tests/test_business_schema_contract.py tests/test_business_schema_metadata.py tests/test_documentation_sources.py --basetemp "build/pytest-$run-e0" -q
& $py scripts/verify_database_design.py
```

**产物/完成**：原五组值及类型等价报告、资源校验反例、DDL字节不变、打包资源可读、说明追踪、完整2节退出证据。任何映射差异未解释、缺资源时仍工作、启动执行DDL，均失败。恢复仅还原本批代码/资源与包，不需要也不得回退业务表。

## 4. E1：财报三表业务包

**路径**：完整表以manifest的E1为准。主要是 `plugins/collectors/ths_statements.py → features/financial_statements/collector.py`，其`chain`归`contract.py`；`plugins/datasets/financial_statements.py → contract.py`，`financial_archive/quality/wire → dataset/quality/wire.py`；data的financial_statements/financial_preparation→query/audit；UI的financial_statements/statement_matrix/statement_preview→ui/statement_matrix/statement_preview。`statement_layouts.json`按真实资源消费者同步到包内。

**实施**：

1. 先迁移三种KINDS、字段布局、金额/报告期/质量和wire版本契约；`chain`是消息/归档契约，不由query反向导入collector执行层。
2. 搬移执行、归档、正式查询和三页，逐项保留原槽位、三task/三dataset/三UI身份、namespace/schema version及后置preparation贡献。`remaining`只移除该族。
3. 财报来源继续使用原JSON响应/解析，不新增HTML依赖。复用D已验收私有存储/verification辅助；把 `scripts/verify_ths_statements.py` 重构为领域核对层。不要恢复旧不安全独立test_storage或从C候选覆盖D共享清理逻辑。
4. 领域验证按随机池独立记录每种报表：来源规范键集合、日期、字段值/金额单位/空值/舍入质量、SQL manifest、统一状态与正式查询、pending0、分析可用性。来源没有公告日期的限制保留；不能将报告期作为公布日期，也不能宣称严格历史回放可用。
5. 三表归档分别验证不变无业务DML、修订、迟到旧响应、SQL提交后重放、冷热摘要、同条数不同业务集合与旧记录补齐。

**验证命令**（相关新测试需先实现并审阅）：

```powershell
& $py -m pytest tests/test_ths_statements.py tests/test_verify_ths_statements.py tests/test_source_verification.py --basetemp "build/pytest-$run-e1" -q
& $py -m pytest tests/integration/test_financial_archive.py --basetemp "build/pytest-$run-e1-sql" -q
& $py scripts/verify_ths_statements.py --pool-config config.toml --test-mysql-settings $testSettings --random-count 30 --seed <记录的随机种子> --proxy-only --output "$out/financial-source.json"
```

最后命令仅在工具安全审阅与专项通过、正常关闭桌面、私有归属验证完毕后执行；默认所有kinds均验收，固定已知失败证券另用`--codes`加入，不代替30股。失败/取消需精确ownership恢复，恢复用共享`--cleanup-only --run-state <确切记录>`，不能扫描删除。

**完成**：三表分别出具结果及三页面可见证据；不可用字段明确限制。当前设计卡是legacy_baseline的部分继续如实保留，不把搬家写成做过新容量实测。任何一表集合/金额/恢复失败，E1不完成；修复来源解析则适用真实代理实采准入。

## 5. E2：指数、行业和指数行情

**路径**：`contracts/indices/industries/index_prices → features/<同名>/contract.py`；各`ths_*` collector/source、datasets、data、UI迁入相应包，index_price_chart→index_prices/chart。`contracts.indices.index_code → contracts/security.py:index_code`保持原语法；行业HTML的Document/Node/one→唯一`sources/ths_catalog_html.py`。

**实施**：

1. 把index_code作为跨业务纯证券标识能力，不让shared security导入indices业务包；拒绝输入及规范化行为与旧函数AST等价。
2. 明确三个bundle各自身份。目录、目录成员和指数年度行情仍用原正式数据集、唯一键及排序，来源共享语法留公共sources，行业规则不反向引用指数collector。
3. 保留指数/行业集合完整性：不仅数条数，还核对业务键、源总数、成员关系、过滤口径；原子snapshot只有完整校验后发布。偏移分页同键跨页重排必须保留处理。
4. 行情保留交易年份计划、年度缺口/404边界/空值规则与来源日边界；不得把不支持年份或失败页当空年度完成。已知历史反例加入固定回归。
5. query/UI与preparation导入公共contract/API，不能依赖其他包private dataset实现；同步全部测试patch字符串及设计卡路径。

```powershell
& $py -m pytest tests/test_ths_indices.py tests/test_ths_industries.py tests/test_ths_index_prices.py tests/test_industry_ui.py tests/test_index_price_ui.py --basetemp "build/pytest-$run-e2" -q
& $py -m pytest tests/integration/test_index_archive.py tests/integration/test_industry_archive.py tests/integration/test_index_price_archive.py --basetemp "build/pytest-$run-e2-sql" -q
& $py scripts/measure_indices.py --test-settings $testSettings --output "$out/indices-capacity.json"
& $py scripts/measure_index_prices.py --test-settings $testSettings --output "$out/index-prices-capacity.json"
```

容量工具先完成2.4安全核查；保持原规模/SQL/阈值，更新`index.catalog/index.members/index.price.status/index.price.year`对应新成功报告。目录类或按指数采集与30股票门槛的适用边界分别说明，不能把随机30个指数写成30股票。

**完成**：三能力独立集合/内容、旧版/重放与正式查询、容量及页面证据；index_code共享权威唯一且无新反向依赖，旧模块退役。任一目录不完整或年度误标完成都失败，不发布部分完整snapshot。

## 6. E3：股票、日历、停复牌、数据准备与目录基础

这是有共享边界变更的一批，不能只当文件搬家。manifest的E3和authority_changes为完整范围。

### 6.1 路径与公共权威

- 股票contracts/stocks及sina/ths_universe、stock_pages、dataset/data/UI进入`features/stocks`；`current_directory`为`api.py`，snapshot marker/指纹身份为`publication.py`。
- cninfo_calendar、trade_calendar及calendar_preparation进入`features/calendar`；月日期/验证纯规则在`contract.py`，正式交易日读取在`api.py`。
- tdx_suspensions、suspension_batches及dataset/data/UI进入`features/suspensions`；源记录身份/规范化/期间校验在`contract.py`，source覆盖与排除能力分`coverage/exclusions.py`。
- 旧`plugins/data/preparation_checks.py`必须拆：stock审计→stocks/audit_rules与audit，calendar审计/快照→calendar/audit_rules与snapshot，suspension审计→suspensions/audit；只有通用evidence/freshness→preparation/evidence。
- `contracts/preparation.py`和`contracts/preparation_scope.py`保留原唯一公共路径。证据/贡献dataclass与PreparationScope不搬家；原research里的STUDIES/FOCUSES原值进入公共scope。research选择、guard、summary和需求catalog属于`features/preparation`，shared scope不导入research。
- `plugins/ui/preview_cards.py`、`preview_navigation.py`、`preview_layout.py`保留原公共位置。它们不能被迁进data_browser再供其他业务反向import；不增加兼容转发。
- data_browser拥有catalog/preview业务组合；core/preparation_release保留资源/发布根读取职责。所有完整目标见JSON，不从已撤销的中间草稿路径迁移。

### 6.2 两项必须单独验证的装配改造

**股票确认回调**：

1. 将原`ArchiveConfirmationPlugin.stock_status`完整业务体提取为`features/stocks/confirmation.py:stock_status(mysql, redis, source, job_key, project_id, snapshot_id)`；除self存储字段改显式参数外保持分支/返回/异常。
2. 新建纯`contracts/confirmation.py`的handler Protocol与ConfirmationContribution；FeatureBundle声明confirmations；DatasetContribution声明所需confirmation标识。stocks明确requires/provides `stocks.snapshot`。
3. builtin装配检查handler合法、同一owner、必需与提供精确相等，重复、缺失、未使用、错误owner均在构造服务前失败；不能缺失时隐式导入股票包补齐。
4. bootstrap在原7200槽注入原ArchiveConfirmationPlugin；provider原ID/dependencies/page_status/start/stop/health保留。协议层不捕获manager、活连接或widget。
5. 实测SQL/Redis错误与取消原样传播，不返回伪complete；中断/摘要丢失/已提交重放的状态判定保持原行为。

**Workspace工厂**：共享WorkspaceUiPlugin只接收惰性factory。data_browser bundle在原14800槽贡献此插件；`contribution.workspace_pages`保留原home/catalog PageContribution、home的top_level、catalog的分类/order/cache，页面类在factory内延迟导入。装配不得创建QWidget、启动定时器或数据库。独立禁用/启用与切页回收按原插件生命周期。

### 6.3 业务不可改变的事实

1. 股票仅一份当前目录、双来源正式归属；publication只有实际变化才同事务更新，不变业务不写，Redis核验标记与SQL上界分别解释。不同证券集合条数相同必须检测。
2. 日历最早1990-12-19，首次补历史至下一自然年12月，以后本月至下一年12月并补SQL缺月。整月校验全部日期、唯一性、跨月与trade标记，缺失不等于休市。未来安排可修订。
3. 日历浏览MySQL不能强依赖Redis；Redis时效补充须摘要/版本/未过期索引与已读SQL月份匹配且不早于SQL，不因验收刷新时间掩盖缺日。
4. 停复牌按source_dates展示来源查询日期，与suspended_at/resumed_at事件生效分开；并列原因、未知复牌及不同复牌时间记录全部保留；旧source_dates缺失不能冒充当天无记录，补采规则保留。
5. 数据准备按实际用途/市场/证券/日期范围检查必需字段和业务集合，开发验证与实际归档分别呈现；scope未知/缓存损坏/缺关联字段不能当通过。研究公布/可用时间限制保留。

```powershell
& $py -m pytest tests/test_sina_universe.py tests/test_ths_universe.py tests/test_cninfo_calendar.py tests/test_tdx_suspensions.py tests/test_suspension_source_dates.py tests/test_calendar_preparation.py tests/test_preparation.py tests/test_preparation_research.py tests/test_preparation_directory.py tests/test_preparation_cache.py tests/test_preparation_progress.py tests/test_workspace_scaling.py tests/test_batch_confirmation.py tests/test_foundation_public_api.py tests/test_shared_boundary_injection.py --basetemp "build/pytest-$run-e3" -q
& $py -m pytest tests/integration/test_stock_archive.py tests/integration/test_ths_stock_archive.py tests/integration/test_calendar_archive.py tests/integration/test_suspension_archive.py --basetemp "build/pytest-$run-e3-sql" -q
```

补充UI反例：未访问页面不创建；切页取消只读查询不取消保存命令；同身份刷新保留选择/滚动；编辑草稿不被回执覆盖；控件滚轮不改值。真实桌面逐页核实导航/数据准备结果/插件偏好。

**容量与完成**：公共preparation协议保留避免15/17旧报告因无收益搬家额外失效，但必须扫描真实绑定；这不豁免E3语义/恢复测试。保留原协议类与scope及选项AST等价证据、15份报告原公共引用验证。三个来源分别有适用证据；handler注入、惰性factory、共享无反向导入全部通过后才结束E3。

## 7. E4：开盘啦七项业务

**前置**：E0 SQL归属与E3公开股票/日历/停复牌/证据输入已发布。七kind为trend、auction、volume、trades、entrust、large_order、quote，分别保留原任务/namespace/表组/页面身份。

**实施顺序**：

1. 按manifest迁移24个原模块并逐符号拆分：`source_protocol`拥有请求常量/选项；parser/pair_parser拥有解析；canonical/normalization拥有业务规范与摘要；schema/storage_contract拥有本业务表组/键；dataset/repository/codec/trade_blocks保留正式写入/查询；dates/scope/listings_source/alias_contract等保持原范围证明。
2. 把共享 `infra/schema_manifest.market_contract()` 更名并泛化为 `schema_contract(tables)`，只接收显式表集合；所有原调用方同批迁到新签名并退役旧入口，KPL在自身包选择自身表组。E0通用business_schema不导入KPL；KPL采用唯一SQL元数据时精确保持原TABLES/KEYS及表顺序。
3. KPL跨业务只使用E3公开API；任何私有dataset/query内部import改为已审公开contract/API，不能搬一个业务类到shared来消除表面依赖。
4. 保留原QuotePage只在quote分支内部延迟导入；普通kind不创建quote控件。公共cards/navigation/layout留公共位置；产品页布局/格式/图表按职责拆分，UI350行上限不放宽。
5. 七kind分别验证股票日范围、分页序号/总量/同秒成交边界、别名/上市日期/停复牌范围、源响应→规范数据→SQL→正式分页与可用性。旧schema可读路径/隔离语义按原契约，不新增运行时转换。
6. 对齐静态assembly、表字典、coverage、README/说明。旧`intraday`的现役职责按manifest进入legacy_pair，名字不表示保留一条旧运行写入路径；如发现确实退役代码按正式调用核实后清退。

```powershell
& $py -m pytest tests/test_kaipanla_source.py tests/test_kaipanla_products.py tests/test_kaipanla_intraday.py tests/test_kaipanla_task_rules.py tests/test_kaipanla_quote_ui.py tests/test_kaipanla_measurement.py tests/test_kaipanla_public_inputs.py --basetemp "build/pytest-$run-e4" -q
& $py -m pytest tests/integration/test_kaipanla_products_archive.py tests/integration/test_intraday_archive.py tests/integration/test_kaipanla_suspension_scope.py tests/integration/test_preview_queries.py --basetemp "build/pytest-$run-e4-sql" -q
& $py scripts/measure_preview_queries.py --test-settings $testSettings --output "$out/kaipanla-preview-capacity.json"
```

**容量**：先集成和验证安全版capacity_session及preview工具。真实只读样本七kind缺一失败；测试库必须包含原100000条同秒trades合成负载。真实日期/实例版本/端口/flush从当前环境读取，不能硬编码旧13331或旧日期。七个`kaipanla.<kind>.day`设计卡同时指向本轮新报告，绑定实际helper/fixture/业务代码/SQL归属资源和loader。原查询/空间预算不变。

旧`kaipanla-storage-capacity-2026-10-05.json`是历史写入实验；冻结v1的`measure_market_storage.py`不是当前v2安全入口，不直接运行。纯组织等价时可明确保留历史写入基线范围；若写入行为、字段或DDL变化，须准备当前契约独立写入实验，不能以查询性能代替。

**完成**：七kind逐项有适用来源/集合/恢复/查询/页面证据和统一归档成功清队。任何一项缺样本、只测quote却概括七项、无实测刷新旧绑定，均失败。源规则实际变化时重建范围证明并执行适用随机30股，不用旧完成状态替代。

## 8. E5：资本行为与复权

**前置**：E3 calendar与E4 KPL公开行情迭代输入已发布；分红容量完整协议缺口已在本批开始前形成可审方案。分红、配股、增发与adjustment既有功能属于本批，但各数据集独立出证据。

**路径/步骤**：

1. 资本contract/validation/archive/issue_detail→`features/capital_actions`；source_protocol、fields、parser、dividend_parser、source/dividend_history/dividend_discovery、lifecycle/recovery/issue_prefetch/issue_source明确拆职责。`result_set`导入必须随parser迁移，不能在拆分中遗漏。
2. collector/query/codec/issue_candidates/UI迁入包；资本事件身份、消息chain、分页/期间计划和修订版本顺序从原实现保留。旧collector不能成为query的公共依赖。
3. `contracts/adjustment`及data/adjustment_inputs/UI/chart进入`features/adjustment`；公开计算契约和业务输入独立。保留资本事件与行情/日历的原同连接读取契约，防止跨时点混合。
4. 验证事件生效日期、报告公布/可用日期、未到期事件不提前使用、复权前后方向/精度/缺值与query范围；不同资本事件不能因字段相似合成错误身份。
5. 保留原完整响应单读/分页顺序/历史发现上限。归档和下载独立，恢复不能先等每一旧批归档才继续下载；只整轮入队后确认全部成功。

```powershell
& $py -m pytest tests/test_capital_lifecycle.py tests/test_capital_recovery.py tests/test_capital_preparation.py tests/test_capital_ui.py tests/test_adjustment.py tests/test_adjustment_query.py tests/test_adjustment_chart.py --basetemp "build/pytest-$run-e5" -q
& $py -m pytest tests/integration/test_capital_archive.py tests/integration/test_issue_availability_archive.py tests/integration/test_adjustment_pipeline.py --basetemp "build/pytest-$run-e5-sql" -q
```

### 8.1 分红容量是明确待解决项

原完整证据含：本轮来源行数≤100000、计划报告期≤1000；SQL全表JSON总字节≤134217728、单payload≤65536；正式`CapitalDataPlugin('dividends').list_events(code='600007', limit=51)`连续10次最大值作为P95上界≤1500ms。历史实采5580证券、56145来源行/629期，SQL56150行含5条保留旧方案，**不能把这些旧数字当作本轮实测**，也不能把SQL数量当来源数量。

可先准备只读诊断`measure_existing_capacity.py --subject dividends --output <新路径>`，它执行精确只读SQL和正式decoder，不启动manager/Redis/网络；正常完成退出2，并明确`not_capacity_gate_evidence=true`。其直接read适配器不包含旧SQLLane等待，只读结果仍缺本轮来源计数/期数，不能用于关闭本批验收或直接更新measured设计卡。

本批实施前完成下面工作，不能留给发布后补：

1. 从正式历史证据恢复旧查询/阈值/样本定义，设计新协议说明范围差异。当前SQL容量通过既有SQLLane执行同一正式query，或明确审阅新的计时口径；保留原阈值。
2. 在D的PrivateStorage独占SQL/Redis内复制只读适用股票池/必要已归档报告期/当前tdx站点与下载配置，冻结范围。运行正式分红来源计划和共享下载/代理一次当前范围观测，保持原请求协议；不改用户任务策略、next_due或断点。
3. 收集真实计划期数、来源规范集合与条数、SQL结果、旧历史差异以及实际proxy/direct/fallback计数；需要严格实采准入则额外满足随机30股和固定反例，允许回退的开发记录不能冒充。
4. 按原上限判断；超过100000/1000如实失败并重新审阅容量设计，不调数值凑通过。来源不可用时保持未完成。
5. 另一选择是至少原规模的私有合成fixture证明SQL工作负载，但它不能证明来源56145/629这两项。若要更换设计卡容量协议须先明确审阅业务取舍，不能无声替换旧“完整measured”。

**完成**：资本各数据集恢复/公开query/事件时间语义、复权计算与UI、真实完整新分红容量证据、2节全部退出项。只读部分诊断成功不等于E5完成。若仅此项仍缺，记录明确阻碍和已做工作，不继续把E5标done。

## 9. E6a：同花顺资本运作

**前置**：D的共享HTML已发布，E0元数据权威存在。`contracts/ths_capital`、ths_capital_source/collector、datasets/data/UI→`features/ths_capital`对应contract/source/collector/dataset/query/ui。公共HTML仍`sources/html.py`，不通过holders私有包导入。

1. 逐原列保存九栏目身份、字段/单位/货币、空值/质量、记录键及旧版顺序；每证券一次HTML解析九栏目，不固化额外重复下载。
2. 迁移本族bundle，仅取走本族槽位/任务/dataset。query和页面使用本包契约，报告范围/观察上界/后续补齐规则保持。
3. 采用E0表组权威，顺序与原九栏目表组一致。工具和新报告绑定实际JSON/loader；D已经因共享HTML重测的报告在本批业务搬家后仍须再次重测。
4. 反例覆盖九栏目不齐、标题/金额/币种变体、旧修订/迟到响应/同条数异集合、提交后重放及页面栏位展示；任何来源解析调整按适用随机30股严格代理验收。

```powershell
& $py -m pytest tests/test_ths_capital.py tests/test_ths_capital_lifecycle.py tests/test_ths_capital_transport.py tests/test_ths_capital_verification.py tests/test_ths_capital_ui.py --basetemp "build/pytest-$run-e6a" -q
& $py -m pytest tests/integration/test_ths_capital_archive.py --basetemp "build/pytest-$run-e6a-sql" -q
& $py scripts/measure_ths_capital.py --test-settings $testSettings --report "$out/ths-capital-capacity.json"
```

**完成**：九栏目来源/正式query、全栏目UI及重放/实采/新容量，设计卡`ths.capital.security`更新；不能复用D的旧绑定而称E6a完成。

## 10. E6b：上市资料、上市状态与证券代码映射

此组允许拆成E6b-listings、E6b-status、E6b-aliases三次独立发布，后者不因前者成功自动完成。

1. `contracts/listings`与ths_listings collector/source/dataset/data/UI→`features/listings`；保留证券键、上市信息必需字段、来源允许范围和历史缺项限制。
2. `contracts/listing_status`及tdx_listing_status/data/dataset/UI→`features/listing_status`；valid_proof与FINGERPRINT_VERSION归contract，月事件/市场身份不变；空月须有合法完整性证明，不能未知即空。
3. bse映射来源/规范/数据集→`features/security_aliases`；URL/LIMIT/validate归contract。原维护发布者继续由明确脚本入口贡献，不能改成后台自动采集。原脚本仍显式调用、保留数据检查与同名锁。
4. 三者分别验证来源集合/正式查询/旧响应和关联字段；映射导入不能覆盖无关证券，不能因为数量1000相同就认为内容完整。

```powershell
& $py -m pytest tests/test_ths_listings.py tests/test_listing_status.py tests/test_listing_scope_prefetch.py --basetemp "build/pytest-$run-e6b" -q
& $py -m pytest tests/integration/test_listing_archive.py tests/integration/test_listing_status_archive.py tests/integration/test_security_alias_archive.py --basetemp "build/pytest-$run-e6b-sql" -q
& $py scripts/measure_listings.py --test-mysql-settings $testSettings --output "$out/listings-capacity.json"
& $py scripts/measure_listing_status.py --test-settings $testSettings --output "$out/listing-status-capacity.json"
```

### 10.1 BSE容量完整复现实验

旧实验来自`tests/integration/test_security_alias_archive.py::test_capacity_1000_rows`。正式迁移后须新增或整合安全`measure_bse_capacity.py`，待审阅/测试/真实执行，不能把准备草稿视为可用工具。

- D共享PrivateStorage/verification要求独立13348、实际server_uuid不同、UUID SQL库/owner marker/同连接锁、独占Redisnamespace；真实配置仅必要身份只读。
- 固定1000行：legacy 830000～830999，unified 920000.BJ～920999.BJ，名称证券0～证券999，listing_date=2020-07-27。
- 计时从读取checkpoint开始，经过统一Redis publish与archive.flush；检查规范/SQL全部集合和内容一致、本轮pending=0。一次有序LIMIT1000查询。
- 原两句额外SQL为`EXPLAIN SELECT * FROM security_code_alias WHERE unified_code='920149.BJ'`和`ANALYZE TABLE security_code_alias`。只在领域子类精确放行这两句且先经基类实际数据库归属验证；其他EXPLAIN/ANALYZE、跨库/多语句仍拒绝，不放宽共享守卫。
- 原阈值：import_ms≤2000、read_ms≤100、allocated_bytes≤1048576，索引ux_alias_security；实际版本/端口/flush如实记录。旧38.9536/4.2103/131072仅历史数字，绝不可复制。
- 先stop manager，再独立清理owned SQL/Redis/锁/连接，核对来源/配置身份不变，完整新报告落盘后才能PASS。清理失败保留ownership记录，不删除猜测库。

```powershell
& $py -m pytest tests/test_existing_capacity_tools.py --basetemp "build/pytest-$run-bse-tool" -q
& $py scripts/measure_bse_capacity.py --test-mysql-settings $testSettings --output "$out/bse-capacity.json"
```

这些是工具实现完成后的命令，目前不存在的工具应按上述契约先实现/安全审阅，不因文档给出命令而假设已存在。该实验不请求BSE来源、不是生产import；30股实采对本合成容量N/A，不证明当前官方映射完整。真实来源/维护入口变化另按其适用规则验收。

**完成**：`listing.detail`、`listing_status.month`、`bse.code_mapping.complete`三项设计卡分别引用新成功报告；每个拆批都有2节退出项。禁止把正式维护导入脚本当容量测量入口在生产库造1000行。

## 11. E6c：更名与ST事件

**路径**：`contracts/name_changes/st_events`，相应tdx collector/source/dataset/data/UI→`features/name_changes`与`features/st_events`。共同EventTimeline等只复用公共UI能力，不互相导入业务页面。

1. 保留名称类型/事件类型、市场范围、来源记录键、并列原文/原因与历史修订；同证券同日期不同文本不能被机械去重覆盖。
2. 保存事件生效日与获取时间区别、旧版本顺序、完整市场单元证明、日期范围查询和分页。当前状态不能冒充全部历史。
3. UI仍可按来源/日期/证券查阅；返回空需与来源支持边界区分。分别证明归档同内容免写、迟到旧响应和提交后重放。

```powershell
& $py -m pytest tests/test_name_changes.py tests/test_st_events.py --basetemp "build/pytest-$run-e6c" -q
& $py -m pytest tests/integration/test_name_archive.py tests/integration/test_st_archive.py --basetemp "build/pytest-$run-e6c-sql" -q
& $py scripts/measure_name_changes.py --test-settings $testSettings --output "$out/name-changes-capacity.json"
& $py scripts/measure_st_events.py --test-settings $testSettings --output "$out/st-events-capacity.json"
```

**完成**：两个names市场数据集、两个st市场数据集独立来源/生命周期证据与新容量报告；不按股票下载的完整市场响应明确30股适用边界，仍验证涉及证券的完整业务集合。任一事件类型丢失不完成。

## 12. E6d：解禁与行业解禁

**路径**：对应contracts、tdx_unlocks/tdx_unlock_industries collector/source、dataset/data/UI→`features/unlocks`与`features/unlock_industries`；共同PAGE/body/results唯一归`sources/tdx_unlock.py`。两个业务包不互相借用私有source。

1. 先提取完全相同来源协议，再迁业务解释与范围；个股解禁group/detail键和行业月键分别保留，不按“都叫解禁”统一成一个错误粒度。
2. 验证月范围、证券/行业集合、汇总与明细关联、金额/数量单位、来源总数、同数量不同集合、旧修订、历史缺口及恢复。
3. 有界预取仍按序校验/入队，失败月不推进；整轮结束再等全部归档，不引入逐月串行等待。
4. 安全复测现有tools；unlocks命令的`--sample`必须是本轮协议要求的真实只读/已审样本及hash，不填写空占位通过。

```powershell
& $py -m pytest tests/test_tdx_unlocks.py tests/test_tdx_unlock_industries.py tests/test_tdx_unlocks_ui.py tests/test_tdx_unlock_industries_ui.py --basetemp "build/pytest-$run-e6d" -q
& $py -m pytest tests/integration/test_tdx_unlocks_archive.py tests/integration/test_tdx_unlock_industries_archive.py --basetemp "build/pytest-$run-e6d-sql" -q
& $py scripts/measure_unlocks.py --test-settings $testSettings --sample <已审阅并记录hash的解禁样本文件> --output "$out/unlocks-capacity.json"
& $py scripts/measure_unlock_industries.py --test-settings $testSettings --output "$out/unlock-industries-capacity.json"
```

**完成**：`unlocks.tdx_month`与`unlocks.tdx_industry_month`独立新容量/查询/恢复证据；共享来源协议只有一份，实际各自范围并未被缩小。行业范围不是随机股票范围，说明适用性，不能替代个股采集的30股要求。

## 13. E6e：业绩与股东变动数据族

**路径**：`contracts/tdx_performance`、tdx_performance collector/source、dataset/data/UI→`features/performance`。现有六kind（五项业绩/股东人数，加股东变动）原UNIT_KINDS、字段字典、来源单元与任务槽位逐项保留。

1. 迁移公共contract后逐kind审parse/规范化/唯一键/旧响应；不能把多kind循环装配变成少了一项而总数仍碰巧相等。
2. 保留公告/可用日期与报告期、null/零/未知区别、金融单位及修订顺序；缺公布信息必须在用途验收明确限制，不能推断提前可用。
3. 完整来源单元历史回查、首次/后续/fresh、中断/Redis丢失后的恢复边界分别对应实现和测试；SQL正式query与页面分别展示真实可用范围。
4. 多kind可共享执行骨架，但来源语义反例按kind独立；股东变动容量证据不能被五项业绩报告替代。

```powershell
& $py -m pytest tests/test_tdx_performance.py tests/test_tdx_performance_lifecycle.py tests/test_tdx_performance_ui.py --basetemp "build/pytest-$run-e6e" -q
& $py -m pytest tests/integration/test_tdx_performance_archive.py tests/integration/test_tdx_shareholder_changes_archive.py --basetemp "build/pytest-$run-e6e-sql" -q
& $py scripts/measure_tdx_performance.py --test-settings $testSettings --output "$out/performance-capacity.json"
& $py scripts/measure_shareholder_changes.py --test-settings $testSettings --output "$out/shareholder-changes-capacity.json"
```

**完成**：六kind精确身份、各自语义和生命周期/正式query/页面证据；五项业绩设计卡与`shareholder_changes.tdx_unit`分别更新新报告。任一kind仅靠其他kind测试推定可用，均不完成。

## 14. E6f：回购

**路径**：repurchases契约、eastmoney_repurchase collector/source、dataset/data/UI按manifest进入`features/repurchases`。

1. 原plan_id、日期、金额、状态/来源修订版本及分页排序不变；同计划修订允许更新，迟到旧响应不得覆盖，来源有多计划不能按证券合成一条。
2. 源分页边界、总量/唯一键集合、停止条件与有界预取保持；失败页不推进，重复/漏页不是合法完成。修复解析按实际30股边界执行。
3. query与页面筛选/详情、公布/可用日期限制保留；归档冷热摘要和SQL提交后重放覆盖同内容无DML且成功清队。
4. 复测脚本显式`--source-proof`指向本轮适用来源证明；不使用默认历史build文件冒充当前来源证据，记录其范围/hash。

```powershell
& $py -m pytest tests/test_repurchases.py tests/test_repurchase_ui.py --basetemp "build/pytest-$run-e6f" -q
& $py -m pytest tests/integration/test_repurchase_archive.py --basetemp "build/pytest-$run-e6f-sql" -q
& $py scripts/measure_repurchases.py --test-settings $testSettings --source-proof <本轮已验收来源证明JSON> --output "$out/repurchase-capacity.json"
```

**完成**：`repurchases.page`新成功容量、分页集合/修订/恢复/正式查询及UI，2节统一退出项。仅新source-proof文件存在而没有实际来源证据不通过。

## 15. E6g：交易规则与剩余声明收束

**路径**：trading_rules契约、rule_sources/规则采集、datasets/data/UI等按manifest迁入`features/trading_rules`。七kind仍为limit_rules、settlement_rules、lot_rules、tick_rules、sessions、stamp_duty、transfer_fee。

1. 保留审阅来源、引用链接/版本、适用市场、有效日期、字段/单位及规则身份；不新增未经审阅自动来源发现或交易约束推断。
2. 规则值与引用表的键/旧版本/归档状态同事务关系保持；相同内容/可信摘要成功清队，旧引用不能覆盖新修订。
3. 各正式规则项目/query逐项核对，不能只有总数量；页面展示适用范围和限制，不把来源不支持项补成推断值。
4. 只有所有先前E批都实际验收、remaining无贡献且调用方为0时才退役`features/remaining.py`；从builtin删除其入口，同步精确assembly映射/架构ownership/说明，不能提前清空整个remaining。

```powershell
& $py -m pytest tests/test_trading_rules.py --basetemp "build/pytest-$run-e6g" -q
& $py -m pytest tests/integration/test_rule_archive.py --basetemp "build/pytest-$run-e6g-sql" -q
& $py scripts/measure_trading_rules.py --test-settings $testSettings --output "$out/trading-rules-capacity.json"
```

**完成**：七个`rules.<kind>.complete`设计卡同步指向新报告，各规则身份/引用/范围和查询证据齐全。不按股票采集，30股不适用须写原因；这不免来源引用准确性和全规则集合验收。最终无遗留未迁业务才勾remaining退役。

## 16. 交给 F 前的总复核

- [ ] E0～E6g每批独立记录真实提交、main远程同步、发布run、实际EXE与可见桌面；未完成的批明确列出。
- [ ] `planned-migrations.json`逐条核对“已落地实际路径/保留公共路径/已撤回草稿”，不将计划JSON改成运行时插件清单；如正式实现与计划不同，补精确理由和实际迁移记录。
- [ ] 所有旧正式调用清退，无转发兼容模块；公共preparation与preview保持唯一原路径；business_schema与schema_manifest不导入具体业务。
- [ ] 前批的D安全辅助、注解、源码验证、容量安全/证据与文档未被候选全文件覆盖；任何额外修复都重新验证其最终输入。
- [ ] 所有active容量报告绑定有效、原预算保留；本轮报告不是修改旧hash生成；分红完整协议缺口已经真实解决或明确E5未完成。
- [ ] 本轮来源/正式数据/开发验证/性能/离屏/真实桌面结论范围分别准确，不把一种证据代替另一种。
- [ ] F接管通用kind-based依赖门禁时审阅并替换/整合E共享→业务规则，不盲叠重复门禁；应用组合根允许显式装配业务，kernel/shared本身不能反向依赖业务。

最后交付需让下一位AI直接获得实际完成事实、当前前像、剩余明确任务及证据位置。只有文件组织草稿、静态证明或文档清单时，状态仍写“待实施/待运行验证”，不能写“架构迁移完成”。
