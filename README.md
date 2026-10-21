# Empire

面向个人的 A 股投资研究桌面系统，使用 Python，优先支持本地 Windows。

第一阶段围绕行情与公告采集、选股和策略回测建设；当前仅提供研究和决策辅助，暂不接入券商或实盘自动下单，保留未来通过插件扩展交易能力的边界。

项目使用小内核与内部插件：稳定内核负责启动、插件生命周期及能力契约，采集、存储、调度和业务页面由内部插件提供。业务代码按功能归拢，纯解析函数和普通控件无需单独注册；下载、代理、归档与调度始终共用唯一公共实现。实施顺序与边界见 [模块化优化方案](docs/architecture-evolution-plan.md)；逐项执行和交接从 [实施与验收手册](docs/architecture-evolution/README.md) 开始。A～F 的组织迁移与公共治理已完成正式发布和同包真实桌面验收；严格来源与历史数据准备的失败范围仍保留，见[最终逐项报告](docs/evidence/architecture-final-2026-10-21.md)和[状态账本](docs/architecture-evolution/status.md)。

Windows 环境直接连接本机运行或已有的 Redis / MySQL 服务，不使用 Docker Desktop 或 WSL2。应用升级与数据库结构修改分开；需要改表时直接在现有 MySQL 中按需执行 SQL，不默认搬迁或重写历史数据。

## 当前状态

新增[通达信重要股东持股变动](docs/tdx-shareholder-changes.md)：每页10000，按变动截止月份完整核验，补充页面日期目录以外历史；公告日期单独保留。

桌面与可靠采集管道已实现，已接入股票列表、财经快讯、交易日历、历史停复牌、分红送转、增发、配股、同花顺三大财报、当前行业、[当前指数及成分](docs/ths-indices.md)以及开盘啦七项独立历史数据（分时、竞价、分钟量额、分笔、委托汇总、大单净额、盘口摘要）。具体来源范围与验证边界见下方说明和实现状态；选股与回测按后续阶段接入。

- [架构设计与实施阶段](docs/architecture.md)
- [需求基线、默认方案与待确定事项](docs/architecture.md#1-需求基线与设计假设)
- [Redis 到 MySQL 的归档与恢复](docs/architecture.md#6-数据管道归档与断点恢复)
- [跨插件共享采集频控](docs/architecture.md#7-跨插件共享采集频控)
- [已实现功能与验证边界](docs/implementation-status.md)
- [Windows 服务与容量配置](deploy/windows-services.md)
- [故障恢复与隔离演练](docs/recovery-runbook.md)
- [依赖与供应链治理](docs/dependency-governance-review.md)
- [独立分发与配置路径](docs/portable-distribution-review.md)
- [文档契约与稳定证据](docs/documentation-governance-review.md)
- [程序内说明维护](docs/documentation-maintenance.md)：修改本业务权威片段，在发布冻结前运行 `scripts/documentation_build.py generate`；`storage_reference.md` 是自动生成资源，禁止手工维护。
- [新浪股票列表：字段、采集与续跑](docs/sina-stock-list.md)
- [当前股票目录：同花顺完整单页与采集任务归档还原](docs/stock-directory.md)
- [开盘啦七项历史数据：范围、独立启用与续采](docs/kaipanla-intraday.md)

数据预览按业务类型呈现：月历、新闻阅读流、公司档案、事件时间线、财报矩阵、行业/指数目录及行情图；精确原值与来源限制保留，跨页跳转带证券身份，返回保留查询状态。详见[桌面操作](docs/desktop-guide.md)。

## 启动

动态代理采集已接入：在采集任务中按项目设置，在网站频控设置各出口和总上限，代理池页面查看在线设备及直连回退。公共策略缺省为代理优先、允许直连回退；用户已保存的选择优先，配置下一轮生效；详见 [动态代理采集](docs/proxy-collection.md)。

当前机器直接双击项目根目录的 `Empire` 快捷方式即可打开，不需要先执行命令。快捷方式启动无控制台窗口的打包程序：

```text
dist/Empire/Empire.exe
```

`dist/Empire` 是完整可搬移程序目录，可整体复制到带中文或空格的可写目录后直接双击其中的 `Empire.exe`。配置固定为 EXE 同目录的 `config.toml`；源码运行使用项目根目录。首次缺配置会生成空白模板并提示填写，不会自动连接或修改数据库。复制带配置的目录会同时复制密码，请勿把真实配置对外分发；打包重建会保留已有本机配置。

开发时也可在项目目录执行：

```powershell
.\start.ps1
```

也可直接运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire run
```

代码或依赖更新后，关闭 Empire，通过正式发布门禁执行环境核对、完整测试、四档离屏布局、打包及隔离 EXE smoke；成功后同时更新根目录快捷方式：

```powershell
.\verify-release.ps1
```

`build.ps1` 与 `verify-release.ps1` 进入同一完整门禁，共享全过程独占锁；直接打包也不能跳过验证。它严格要求 Python 3.12、PyInstaller 6.22.3、一致依赖和当前锁对应的依赖报告，不自动安装构建依赖。测试、打包和 smoke 在本次拥有的暂存目录完成后才切换正式程序，失败保留原包与程序配置。构建身份在“系统设置 → 运行状态”查看；`build/release-report.json` 和 `build/releases/<本次标识>/publication.json` 绑定源码输入、提交、测试与依赖证据和产物摘要。中断恢复使用 `verify-release.ps1 -Recover`，正常关闭程序后执行，不删除锁文件。详见 [发布门禁](docs/release-gate-review.md)。容量报告只使用虚拟目录和模拟响应，不访问真实代理或公开源站，详见 [隔离容量与资源稳定性验收](docs/capacity-evidence-review.md)。

桌面默认打开“工作台”，左侧一级菜单为工作台、数据浏览、采集管理、系统设置、说明文档；工作台与说明文档直接打开，其他分类通过二级菜单切换页面。采集任务管理手动执行、固定间隔、每日定时与请求重试；运行记录和网站频控分别有独立页面。任务默认按插件的推荐计划配置，已保存设置优先；自动任务在程序运行且计划到期时执行。

“采集管理 → 下载资源”支持按 100、200 至 1000 台规划出口设备一键生成容量推荐，默认 100 档为 128 下载窗口和 512 MiB 共享缓冲；也可分别设置单响应/文件大小、磁盘配额及文件并发。推荐只填容量草稿，不修改网站每 IP 频控或任务代理开关；保存到 MySQL 后正常重启软件生效，不中断当前采集。设备数不等于独立出口 IP 数，实际并发随在线出口、网站规则、预算和页数变化。详见 [下载资源边界](docs/download-resources.md) 与 [出口容量验收](docs/exit-capacity-review.md)。

股票列表页支持沪深北市场筛选、搜索、分页与复制选中行（Ctrl+C），只展示最新完整归档结果。界面操作见 [桌面使用说明](docs/desktop-guide.md)。详细说明见 [采集中心与统一管理](docs/collection-management.md)。也可关闭桌面后运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire collect-stocks
```

项目统一代码采用 `000001.SZ`、`600519.SH`、`920000.BJ` 格式，原始六位代码保持字符串类型。

本地密码位于程序目录 `config.toml`；可以用 `EMPIRE_MYSQL_PASSWORD` 和 `EMPIRE_REDIS_PASSWORD` 环境变量覆盖。日志、单实例锁和插件启停偏好仍位于 `%LOCALAPPDATA%\Empire\`，采集断点位于 Redis。旧用户配置或旧版 `config/local.toml` 通过 `python scripts/migrate_program_config.py --source <旧文件> --destination <目标config.toml>` 显式复制，拒绝覆盖不同目标，不作为运行时兼容路径。任务与网站频控配置保存到 MySQL，电脑重启后仍保留。当前版本数据库升级须正常退出后显式运行 `python scripts/migrate_collection_state.py`，详见 [统一状态维护](sql/changes/2026-09-26-collection-state.md)。

## 新环境准备

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
Copy-Item config/app.example.toml config.toml # 仅首次源码配置；已有文件不要覆盖
```

编辑本地连接配置后，执行只读检查与首次建表：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m empire doctor
.\.venv\Scripts\python.exe -X utf8 -m empire init-db
```

`init-db` 在目标数据库按 `sql/schema.sql` 创建缺失的正式表，包含股票、新闻、日历、停复牌、增发送配、三大财报，以及 `collection_state` 统一状态表和 `app_setting` 配置表；应用启动不自动改表。已有表的结构升级通过对应显式维护入口执行。

已有项目排错可运行 `python -m empire doctor --project sina-news --output diagnosis.json`；需要具体错误正文时增加 `--error-id <确切ID>`。报告只读、有次数/时间/体积预算，逐项显示取得的证据和未完成原因；不会启动采集、归档或清理错误，有限查询不替代完整性验收。桌面进程内的即时隔离状态无法从 CLI 获知时明确显示未知。用法与限制见程序内“任务失败与数据未更新”。

## 开发入口

每次任务先按 [开发、排错与交付流程](docs/development-workflow.md) 确认范围、共享工作区、反例和验收证据。该文档包含任务记录模板，并区分现有门禁和待建工具，不新增用户逐步审批。

新增或修改采集功能先阅读 [项目协作约定](AGENTS.md) 和 [新增采集功能开发指南](docs/collector-development-guide.md)。指南集中说明插件登记、公共下载/入队/归档路径、业务专项测试和交付核对清单；不要求复制既有采集器或新增通用框架。

## 验证

```powershell
.\verify-release.ps1
```

完整门禁先核对依赖及文档契约，再使用隔离测试命名空间访问本地 Redis/MySQL，不清空共享数据、不执行结构迁移，也不会发布到外部。文档契约覆盖相对链接、正式表、配置位置、容量默认值、Redis/MySQL 持久化边界和脱敏发布基线。仅做快速开发检查时仍可分别运行 Ruff、Mypy 和目标测试，但不能把它称为发布验收。

集成测试默认跳过。需要连接已配置的服务时显式开启：

```powershell
$env:EMPIRE_INTEGRATION = '1'
.\.venv\Scripts\python.exe -m pytest tests/integration -q
Remove-Item Env:EMPIRE_INTEGRATION
```

集成测试使用独立命名空间和随机事件身份，只清理本次测试的数据。不会清空 Redis 或业务表。

存储说明位于“说明文档 → 数据库参考”，每张 MySQL 表、每类 Redis 键都有独立结构、归属与生命周期条目，可离线搜索。仓库入口为 [数据库参考](docs/database-reference.md)。运行记录页面分为采集、归档、错误三个标签：每个项目分别保留最近 100、100、300 条，仅存 Redis，不归档。

MySQL 使用 stock 保留当前股票列表、collection_state 保留每项目一条已归档状态、finance_news 保留历史新闻、trade_calendar 保留交易与休市日期、suspension_event 保留沪深 A 股停复牌事件；不保存每日完整股票快照或成功 HTTP 原文。规范化业务数据进入 Redis 后立即唤醒统一归档器，60 秒周期扫描作为恢复兜底；事务提交、确认已有相同内容（含可信摘要命中）或确认消息过时后，均删除对应队列消息。失败保留重试。统一 SHA-256 摘要默认每数据集/来源最多 10000 条、7 天过期，可信缓存命中完全不访问 MySQL，缓存缺失自动回 SQL 核对，详见 [统一归档去重](docs/archive-deduplication.md)。错误原文样本只留 Redis，每条最多 64 KiB，并保存脱敏、截断和摘要信息。

错误应先修复并验证，再选中具体记录清除。清除使用精确记录 ID，不影响操作期间新产生的错误；查看页面和后续采集成功都不会自动清理。

新浪财经新闻的增量范围、断点和使用方法见 [新浪 7×24 新闻](docs/sina-news.md)。在“财经快讯”查看结果，在“采集任务”设置自动更新；新任务默认仅手动。

按最新确认，Redis 采用纯内存模式，服务或电脑重启会丢失待归档数据、断点、下次执行时间和记录；配置仍在 MySQL，启动后重建计划。只重启应用可恢复原运行状态。新闻每页 50 条，初始化仅第一页，后续接上上轮 ID 即停止翻页。所有数据插件应跳过完全相同内容的业务写入；股票无变化不替换，新闻和日历无变化不刷新观测时间。MySQL 已重启应用日志关闭配置，并已清理旧日志；redo/undo 为正常运行所需文件。维护详情见 [减少磁盘写入](sql/changes/2026-09-23-low-write.md)。

[巨潮 A 股交易日历](docs/cninfo-calendar.md) 首次补齐 1990-12-19 至下一年年底，之后维护本月至下一年 12 月，并补齐历史缺月。在“交易日历”按月查看交易、休市及未采集日期，在“采集任务”设置更新计划。命令行入口为 `python -m empire collect-calendar`。

后台按多项目规模组织：数据目录按分类/来源检索，任务列表和采集记录分页，详情独立展示，业务页面按需创建；见 [可扩展工作区](docs/scalable-workspace.md)。

通达信增发送配新增 `dividend_plan`（分红送转）、`additional_issue`（增发）、`rights_issue`（配股）三张独立业务表，仍共用 `collection_state` 每项目一行状态。旧建表脚本 `scripts/migrate_capital_actions.py` 已退役，应用启动不改表；现行历史契约维护入口为 `scripts/migrate_dividend_identity.py` 与 `scripts/migrate_issue_availability.py`。分红现按报告期单次容量10000批量取历史，旧@1/@2须关闭程序运行 `scripts/migrate_dividend_identity.py` 无损维护；增发、配股原本已用10000容量。生命周期、来源口径与操作见 [通达信增发送配](docs/tdx-capital-actions.md)。

## 已接入数据与说明（2026-10-01）

“数据浏览 → 数据目录”可查询股票列表、财经快讯、交易日历、历史停复牌、分红送转、增发、配股及利润表、资产负债表、现金流量表。按名称、分类、来源或表名搜索，选择记录查看明细；各采集项目在“采集管理 → 采集任务”独立设置计划。

“数据准备”按因子研究、策略回测、长期价值研究选择必需输入；支持MySQL库存精确盘点、来源集合完成筛选、缺口与JSON导出，首次打开不自动全库深检。检查每份数据的声明范围、缺口与用途；目录里的规划项不代表已开发，采集完成也不代表质量和历史信号用途全部通过。增发送配显示成功入队、核验证券、失败和连续进度，成功入队不等于全部归档，有缺口不能显示完成。

程序内“说明文档”已按入门、日常操作、数据说明、故障处理、数据库参考、技术参考整理，支持离线全文搜索；增发送配和三大财报有独立说明主题。详细来源规则见 [通达信增发送配](docs/tdx-capital-actions.md)、[增发详情](docs/tdx-issue-details.md)、[同花顺三大报表](docs/ths-financial-statements.md) 和 [数据准备](docs/data-preparation.md)。财报金额含来源舍入，缺值及合计矛盾在来源质量中标记；无公告日期，不宣称历史公告前选股可用。实采范围以各项目证据和当前查询为准。

说明文档支持跨分类搜索、本页章节跳转和相关主题导航。开发维护与自动覆盖门禁见 [说明文档维护](docs/documentation-maintenance.md)。

当前行业：已接入同花顺 thshy 行业名单与成分股票，每行业以 size/1000 单次获取完整响应，只保留最新集合，不记录变化历史；从数据目录浏览，并在数据准备独立验收。详见 [同花顺当前行业](docs/ths-industries.md)。

## 2026-10-05 开盘啦七项拆分

分时走势与开盘竞价拆为独立项目，并新增分钟量额、分笔、分钟委托汇总、大单净额、历史盘口摘要，共七项采集/查询/UI 插件。共享 `stock_market_day` 的类型、证券、日期业务键，沿统一 Redis 入队与归档；重复内容及仅元数据时间变化不写业务表。新增任务默认停用，开发与重启不会启动全历史采集。旧合并任务由显式维护入口迁移，启动不自动转换。日常操作、生命周期和限制见 [开盘啦七项历史数据](docs/kaipanla-intraday.md)。

## 开盘啦存储与设计门禁

七项各自使用证券日业务头与类型化事实表，分笔按200点无损压缩块保存；数据页从SQL有界分页，覆盖规划只读业务头。旧证券日JSON通过显式维护入口迁移，启动不改表。字段、公共设计门禁及容量限制见[业务设计规范](docs/database-design-standard.md)和[实施方案](docs/kaipanla-storage-optimization-plan.md)，当次结果见[交付证据](docs/evidence/kaipanla-storage-optimization-2026-10-05.md)。


通达信公司全称与股票简称更名分别接入采集与浏览，默认每天北京时间18:00核验全部来源历史；采集完成与缺名/断链数据质量检查分别显示。见[公司与股票更名](docs/tdx-name-changes.md)。
上市与发行资料：同花顺发行详情已接入独立任务，逐证券补齐当前沪深北股票池，默认每天18:00补缺、每七天回查。数据浏览搜索“上市与发行资料”；不提供完整退市证券及重新上市历史。新表显式维护及字段/恢复见[说明](docs/ths-listings.md)。

## 通达信暂停恢复终止上市

独立采集、查询和数据目录页面保存暂停、恢复、终止上市三类事件，日期取来源日历。默认每天北京时间18:00补缺并回查最近一个月，已保存计划优先；不推算最后交易日，不宣称完整重新上市历史。初始化查询范围1990-12-19至本轮启动日，支持范围不代表已采完。来源、生命周期、结构化事件表及显式新增表入口见[暂停恢复终止上市](docs/tdx-listing-status.md)。

自算复权因子与前后复权行情：从数据目录搜索“复权因子”，复用已归档通达信事件和开盘啦收盘后价格，展示完整范围日K线、均线与缩放，严格复权缺输入或方案歧义不输出；原始行情仍可独立查看。范围及操作见[复权说明](docs/adjustment-factors.md)。

说明入口使用分组目录和摘要，数据手册采用统一章节；源码变化须核对受影响功能的对应说明，采集任务与数据页均有覆盖登记。正式维护入口见 [说明文档维护](docs/documentation-maintenance.md)。

北交所官方历史新旧代码关系可显式导入并按两端代码查询，见[代码映射说明](docs/bse-code-mapping.md)。

指数历史日行情已加入独立同花顺任务与数据浏览：YYYY补齐历史年度，last更新近期开高低收和量额；每天18:00，已保存配置优先。使用范围见[指数日行情](docs/ths-index-prices.md)。

通达信实施ST与撤销ST为两个独立任务与数据浏览页，默认每天北京时间18:00完整核验，保存前后简称、原因及行业；不单独裁定每日ST状态。详见[来源说明](docs/tdx-st-events.md)。

数据准备范围现按 A 股日频回测、股票估值及股东/资金流/融资融券策略因子筛选；具体保留与移出项见[用途范围](docs/data-preparation-scope.md)，日常入口与缓存行为见[数据准备](docs/data-preparation.md)。现有新闻采集和业务记录保留。

交易规则与税费七项独立任务支持已审核官方文件初次核验及3天计划，参数与必要引用结构化共享存储；沪深北2026普通竞价规则、印花税2022/2023生效段和过户费2022公告分别采集。本次只需当前规则；沪深数值T+1交收依据、当前递增数量、北交所涨跌价舍入及现行过户费完整表仍未满足数据准备；见[规则范围](docs/trading-rules.md)。

东方财富股票回购：`eastmoney-repurchases`任务与`stock_repurchase_plan`正式表，数据目录按需打开方案列表及详情；固定2000ms、每日18:00全量核验。字段、生命周期、显式建表和容量证据见[股票回购](docs/eastmoney-repurchases.md)。回购完成不推断注销。

## 通达信财报解读五项（2026-10-12）

业绩预告、快报、披露时间、报告及股东户数分别登记独立任务、结构化表、查询和按需数据页面。每页10000已实测；四报告按季度完整响应并行预取，户数按证券历史预取，按序校验入队，整轮后等待归档。实际已归档进度与最终部署见带日期证据，不以接口支持范围冒充采完。操作、字段、恢复及限制见[通达信财报解读](docs/tdx-performance.md)。

同花顺前十大股东、前十大流通股东、十大债券持有人由一个股东研究任务一次下载全部栏目，保留三个数据目录页，共用结构化 `holder_report` / `holder_member`。每日18:00、代理优先，新任务初始停用；当前页面窗口、变动公告与来源缺序号限制见[持有人说明](docs/ths-holders.md)。

大小非解禁个股与对应股东明细通过一个通达信任务采集，列表参数10000000；列表事实与共享请求组明细分表，完整月市场统一归档。使用、生命周期、来源日期限制及验证范围见[大小非解禁]( docs/tdx-unlocks.md)。

采集任务提供“运行详情 / 任务配置 / 采集规则”，可逐任务查看接口参数、生命周期、日期边界和Redis/MySQL去向；维护遵循[采集规则规范](docs/collection-rules-standard.md)。

同花顺股东研究的名单边界、债券并列排名、退出未知比例及栏目未提供规则见 [持有人说明](docs/ths-holders.md)。来源异常继续后续证券并保留首缺口，整轮失败不冒充完整；错误排查结果见 [本次处理记录](docs/evidence/ths-holders-errors-delivery-2026-10-14.md)。

支持通达信大小非解禁行业：可得月汇总数量、市值及比例，保存估值基准日，数据目录搜索同名数据。

同花顺股东研究保留来源比例缺值和汇总矛盾原值，查询显示来源质量异常；数据准备分别核验集合覆盖和质量限制。必需数量/身份/日期及结构错误仍保留断点，继续后续证券。

公司资本运作（同花顺）：募集资金来源、项目投资、收购兼并、股权投资、参股IPO、股权转让、关联交易、质押/冻结及解除；一次响应全部栏目，原币种与已存历史保留。入口和限制见 [使用说明](docs/ths-capital.md)。

## 公司行动与复权代码定位

[通达信增发送配](src/empire/features/capital_actions/README.md) 与 [自算复权](src/empire/features/adjustment/README.md) 各有独立业务包；复权通过公开规范读取已归档事件和行情，并在同一个数据库快照中验证输入。

股东回报首批：数据准备保留主题总检查，并在分红具体产物及分红送转页面提供闭区间已实施名义每股含税派息汇总；不是到账现金。股息率、持仓现金、回购汇总及稀释未实现，原历史失败保留。见[本批状态与矩阵](docs/evidence/shareholder-return-p0p1-2026-10-22.md)。
