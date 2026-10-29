# Empire 桌面重构设计评审稿

2026-10-28 · 当前阶段：交互与视觉预览、架构评审；**生产客户端尚未迁移**。

用户已选择 React + Ant Design，并确认：**使用桌面 EXE，接受内部嵌入网页引擎；不是要求部署网站**。现阶段先查看整体配色、布局与使用方式，再进入正式迁移。本目录是隔离设计预览，不是第二条正式业务路径。预览中的示例状态、数据和操作不代表真实采集、查询或保存结果。

## 1. 本次要解决的问题

- 功能难找：统一导航、功能搜索与数据目录，使用业务名称定位，保留来源与表名检索；搜索结果、菜单和关联入口指向同一路由。
- 表格不方便：统一列宽、显隐、排序、筛选、密度、选中与复制、分页和详情。完整结果排序必须由正式查询支持；仅当前页排序要明确标注。
- 布局与样式混乱：统一字体层级、间距、颜色、图标、反馈和滚动规则；每页按任务设计信息层级。
- 状态难理解：优先呈现当前结果、异常及可执行动作，技术诊断按需展开。数据未知、来源缺口、查询失败不能被配色或文案改成成功。

交付边界是可运行预览和可审阅方案。预览用于确认设计方向，不以少数演示页代替全客户端迁移，也不以构建成功代替真实桌面验收。

## 2. 技术路线与版本边界

| 层次 | 选择 | 当前含义 |
| --- | --- | --- |
| 桌面外壳 | Electron 45.1.0 | 本目录已声明该版本；正式应用生命周期尚待接入 |
| 界面 | React 19.3.1、TypeScript | 使用统一组件和页面路由；不承载业务数据库逻辑 |
| 组件库 | Ant Design 6.6.8、Ant Design Icons | 本次预览使用核心组件 |
| 页面构建 | Vite | 开发服务器仅供本地预览；正式 EXE 加载打包后的本地资源 |
| 业务后端 | 现有 Python Runtime 与插件服务 | 保留唯一正式查询、命令、采集与归档路径 |
| 进程通信 | stdio IPC | 正式迁移目标；当前预览不连接生产后端 |

截至本轮版本核查，ProComponents 2.8.10 的声明依赖支持 Ant Design 4/5，与 Ant Design 6 不匹配，**本次不引入 ProComponents，也不声称已支持**。正式实施前锁定并验证兼容矩阵；若将来采用，只作为同一 Ant Design 体系的组件，不建立第二套 UI 框架。具体安装版本以本目录 `package.json`、`package-lock.json` 为准。

明确推荐 Electron。pywebview 的安装体积较小，也能承载 React；本项目页面多、表格及交互复杂，Electron 更便于固定浏览器版本、桌面进程管理、调试和自动化。其体积、内存及 Chromium 更新成本须纳入基线实测，不预先宣称更快或更省资源。

## 3. 全量迁移范围

权威盘点见 [route-inventory.json](route-inventory.json)：通过项目现有 `scripts.assembly_contract.snapshot` 读取示例配置和页面声明导出，确认 **64 个页面，50 个登记到数据目录**。复现入口为 [qa/export_routes.py](qa/export_routes.py)，不启动服务、不读取真实凭据。该清单表示已有路由及迁移范围，不表示新界面已经实现。

| 页面组 | 数量 | 现有页面与路由 |
| --- | ---: | --- |
| 工作台与研究入口 | 4 | 总览 `home`、市场复盘 `market_review`、数据准备 `preparation`、数据目录 `catalog` |
| 证券与基础资料 | 10 | 股票 `stocks`、日历 `calendar`、发行资料 `listings`、上市状态 `listing_status`、公司/股票更名 `names_company` / `names_security`、实施/撤销 ST `st_implementation` / `st_removal`、停复牌 `suspensions`、行业 `industries` |
| 指数 | 2 | 指数及成分 `indices`、指数日行情 `index_prices` |
| 股票行情 | 9 | 远航历史 `yuanhang`、复权因子与行情 `adjustment`；开盘啦 `kaipanla_trend`、`kaipanla_auction`、`kaipanla_volume`、`kaipanla_trades`、`kaipanla_entrust`、`kaipanla_large_order`、`kaipanla_quote` |
| 公司行动 | 5 | 分红 `dividends`、增发 `additional_issues`、配股 `rights_issues`、资本运作 `ths_capital`、回购 `repurchases` |
| 财务 | 7 | 利润表 `income`、资产负债表 `balance`、现金流量表 `cashflow`；业绩 `earnings_forecast`、`earnings_quick`、`earnings_disclosure`、`earnings_report` |
| 股东 | 7 | 前十大股东 `top_holders`、流通股东 `float_holders`、债券持有人 `bond_holders`、股东户数 `holder_count`、持股变动 `shareholder_changes`、个股解禁 `unlocks`、行业解禁 `unlock_industries` |
| 涨跌停与题材 | 2 | 远航涨跌停 `yuanhang_limits`、开盘啦题材 `themes` |
| 资讯 | 1 | 财经快讯 `news` |
| 交易规则与费用 | 7 | `rules_limit_rules`、`rules_settlement_rules`、`rules_lot_rules`、`rules_tick_rules`、`rules_sessions`、`rules_stamp_duty`、`rules_transfer_fee` |
| 采集管理 | 7 | 任务 `collection`、归档任务 `archived_tasks`、记录 `history`、站点规则 `sites`、出口 `proxies`、资源 `downloads`、身份 `identities` |
| 系统与文档 | 3 | 运行状态 `system`、插件 `plugins`、说明 `help` |

每一路由须登记新位置、保留能力、采用的公共模板、专项反例和验收结果。生产启用/停用插件仍可改变当时可见页面；不将静态清单全部强制显示。

## 4. 页面与公共组件分工

公共层统一导航、搜索、标题/工具栏、通知、空态/加载/失败/过期态、表格、筛选、日期范围、证券/指数选择器、详情面板、保存栏，以及图表、日历、时间线、报表矩阵的交互规范。正式业务表格保留精确值及业务键，视觉格式不能改写查询结果。

页面仍按用途重新设计：

- 总览显示数据更新与需要处理的事项；数据目录负责全量功能发现。
- 采集任务明确分开运行、配置与规则，保留批量操作及草稿；配置保存结果与运行结果分别反馈。
- 市场复盘组织日期、指标、图表和题材联动；缺少数据时说明实际缺口。
- 财报保留科目层级、完整科目、单位、报告期与来源缺值；股东和公司行动保留主从关系及长说明。
- 新闻保持连续阅读，更新提示不替换正在阅读的内容。
- 行情保留午休/缺点断线、竞价同分钟多点、分页明细范围；事件页分别显示来源日期、生效日期和公告日期。
- 数据准备区分开发状态、已采范围、质量与用途；运行记录、身份管理、下载资源保留各自命令后果及生效时机。

整体配色、密度和布局以本轮预览供用户评审；审阅通过前不把预览样式推广到生产。

## 5. 正式架构及唯一业务路径

```text
Empire.exe / Electron main
  ├─ BrowserWindow：React + Ant Design
  │   └─ preload：有限且有类型的桌面 API
  └─ EmpireBackend.exe / Python bridge
      └─ Runtime → PluginManager → 现有 query / control / collector / archive
```

React 管理显示与交互状态；Electron 管理窗口、子进程、IPC 和必要的系统交互；Python 独占业务规则、SQL/Redis、调度、下载、代理和归档。桥接只做受控操作映射、参数/结果校验、取消和生命周期管理，不重写查询、不增加 SQL 双写或另一归档器。正式方案无需部署网站或开放 HTTP 业务端口。

具体接入点：

- `src/empire/core/runtime.py`：保留 `invoke()` 与 `command()` 作为内部服务入口，增加桥接所需请求/命令跟踪。不得对 renderer 直接暴露任意 `capability + method`。
- `src/empire/bootstrap.py`：保留唯一业务装配、依赖图和归属校验；移除对 Qt 页面实现的导入。
- `src/empire/contracts/ui.py`：把 `PageContribution.factory` 改为可序列化且受控的 `view_key`，保留路由、目录、缓存和 `NavigationContext` 契约。
- `src/empire/plugins/ui/plugin.py`：UI 插件贡献纯元数据，继续使用既有插件 ID、能力和偏好；停用界面不停止采集。
- React 使用静态组件注册表按 `view_key` 懒加载，不按后端字符串加载任意脚本。构建校验页面贡献与组件完整对应。
- `src/empire/__main__.py`：增加正式 bridge 入口，保留 doctor、显式维护与采集 CLI；完成切换后退役 Qt 外壳及旧页面实现。

本次可以保留 Runtime 的 asyncio 线程，避免同时重写调度。桥接读写不能阻塞业务事件循环。

## 6. 通信与状态契约

建议使用 JSON-RPC 2.0 语义、UTF-8 和 `Content-Length` 分帧。stdout 只放协议，stderr 仅放有界脱敏诊断；请求、结果、排队量分别按操作设上限，大结果继续分页。

| 项目 | 约定 |
| --- | --- |
| 启动握手 | 协议版本、后端会话 ID、前后端构建身份、可用页面/操作；失配明确拒绝 |
| 操作登记 | 后端声明 `read / mutation / lifecycle`、参数与结果 schema、大小上限、取消策略；不信任客户端自报类型 |
| 查询身份 | `request_id + scope_id + generation`；新查询替代旧查询，迟到响应不得覆盖新结果 |
| 取消 | 仅取消页面只读请求；SQL 已执行时仍由现有 `SQLLane` 等待真实线程结束并收回资源 |
| 写命令 | 应用级 command store 持有，切页/卸载不取消；同会话按 `operation_id` 去重并可查询结果 |
| 断线/超时 | 区分未执行、已执行、结果未知；后端重启后不自动重发写命令，先查正式状态 |
| 事件 | 带会话 ID 与递增序号；状态可合并，命令结果不可静默丢弃；发现缺口重新读取当前快照 |
| 数据类型 | `null` 保持未知；精确金额和超出 JS 安全整数范围的数值使用字符串；日期/时区明确 |
| 错误 | 稳定错误码、可读脱敏消息、可重试性及执行边界；无任意 SQL/shell/Python 方法入口 |

React 查询库必须显式约束挂载、焦点、重连刷新及重试；写操作默认不自动重试。请求去重和取消不能被描述为跨进程重启的“恰好一次”保证。命令状态只做有界运行态管理，不为 UI 新增业务历史库。

## 7. 配置、单实例和关闭

**配置：**建议 `EmpireBackend.exe` 与 `Empire.exe` 同目录，继续复用 `core/config.py` 的程序目录默认 `config.toml`；源码仍用项目根目录。后端放入 `resources/backend` 后直接沿用 `sys.executable` 父目录会读错配置。也不能简单每次传 `--config`：现有默认缺失会生成模板，显式路径缺失则报错，两者语义不同。Redis/MySQL 凭据不发送到 renderer，真实配置不进入公共包；发布保留已有配置。

**单实例：**Electron 锁用于第二次启动聚焦已有窗口；Python 继续取得 GUI/CLI/维护工具共用的现有业务锁，直到真实退出才释放。Electron 锁不能替代该锁。本轮可复用 `QLockFile` 这一基础设施实现；若要换掉 QtCore 锁，必须一次迁移所有入口并验证跨版本互斥，不能并存两套业务锁。

**打包：**当前 `Empire.spec` 为 `console=False`，不能把原 GUI 包直接当 stdio 后端。正式后端需 console 构建，由 Electron 以隐藏窗口、`shell:false`、管道连接启动。Electron、React 资源、Python 后端及协议/schema 必须形成同一发布身份。

**正常关闭：**进入 `quiescing → stopping → closed`，拒绝新业务操作、取消只读查询、等待已接收写命令取得真实结果，再执行原 Runtime/PluginManager 的逆依赖关闭，等待采集、归档、SQL lane 和线程结束，释放锁后退出 Electron。数据库故障时允许按现有规则保留 Redis 待归档消息，不能声称退出前必然全部清队。

关闭超时显示实际阶段并继续正常等待，不强杀后端/数据库、不删锁、不直接跳过收尾。renderer 崩溃不重启后端或重放命令；Electron main 退出造成 stdin EOF 时，后端执行同一收尾路径。后端异常退出则显示服务中断及未知结果，禁止静默再启动并重发业务操作。

## 8. 必须保留的行为与验证依据

| 行为 | 现有主要回归入口（迁移后保留语义） |
| --- | --- |
| 按需建页、隐藏停止只读工作、LRU 恢复、写入不随切页取消 | `tests/test_page_lifecycle.py`、`test_identity_ui.py` |
| 丢弃迟到查询、区分草稿与已应用条件 | `test_stock_ui.py`、`test_news_ui.py`、`test_market_review_ui.py` |
| 刷新/保存回执不覆盖新编辑，失败可重试，保存值与生效值分开 | `test_collection_ui.py`、`test_download_settings_ui.py` |
| 业务键保持选择与滚动，复制保留前导零，跨来源不串选 | `test_stock_ui.py`、`test_preview_polish.py` |
| 证券市场/指数来源/任务上下文及返回保持 | `test_navigation.py`、`test_index_price_ui.py` |
| 滚轮不改值但页面可滚动，键盘焦点及辅助名称可用 | `test_desktop_interaction.py`、`test_accessibility.py` |
| 未知不等于零/休市/成功，来源缺口及 Redis-only 正确展示 | `test_calendar_ui.py`、`test_holder_ui.py`、`test_yuanhang_limits_ui.py` |
| 仅清除已验证的精确错误 ID，保留并发新记录 | `test_records_ui.py`、`test_log_clear_ui.py` |
| 插件独立启停，外壳与公共组件不依赖业务页面 | `test_ui_architecture.py`、`test_ui_architecture_counterexamples.py` |

Qt 专属测试不能原样证明 React 正确；应把业务反例迁到桥接契约、组件交互和 Electron 端到端测试。迁移相关架构检查时保持职责边界，不通过改名、压行或无理由放宽上限规避。

新增必须验证：半帧/超大帧/协议污染、IPC 背压、版本失配、重复点击、页面重建、父进程 EOF、后端异常退出、关闭中未完成 SQL、不同工作目录、已有配置保留、与维护 CLI 互斥。所有页面覆盖正常/空/加载/失败/旧数据/长内容及窄窗口状态；表格验证排序范围、分页、列设置、复制和业务身份。

## 9. 分阶段实施与退出条件

| 阶段 | 工作与边界 | 退出条件 |
| --- | --- | --- |
| A 设计评审（当前） | 隔离预览、64 路由盘点、整体风格与架构说明；不连接生产业务 | 预览可打开并记录实际验证；用户确认整体配色、密度、导航与高频交互方向。未确认不推广生产 |
| B 桌面与桥接基础 | Electron 外壳、Python 唯一后端、协议、配置、共用锁、生命周期、页面元数据 | 隔离契约/端到端反例通过；声明与组件清单可核对；关闭/断线不丢命令归属，不启动第二后台 |
| C 公共组件与高频流程 | 导航搜索、目录、任务、记录、设置及表格/查询/草稿公共层 | 查询取消、写入独立、草稿竞争、批量操作、精确清理均通过；只称已完成对应范围 |
| D 全量页面迁移 | 按表格/报告/事件/行情/阅读等类型迁移全部业务及系统页面 | 64 路由逐项能力与专项反例通过，目录/跳转/插件启停完整，无遗留旧界面生产入口 |
| E 正式切换与交付 | 退役旧 Qt UI、同步正式说明和实施记录，更新统一发布门禁 | 同一构建身份通过门禁；正式 EXE 验证数据库查询、配置保留、真实桌面及正常退出；明确未测范围 |

实现阶段按本阶段成果推进，不新增常规逐步审批。当前用户已要求先看整体设计，因此设计确认是此次进入生产重构前的既有边界。不同阶段不同时运行两套正式客户端/归档器；开发预览及隔离测试不写生产数据。

## 10. 交付判断

最终“完成”须同时满足全路由覆盖、关键业务反例、正式查询路径、配置与单实例、正常退出、发布一致性和真实桌面操作。对照目标屏幕与 DPI 检查文字不遮挡、表格可用、关键按钮和保存栏可到达、滚动符合预期；离屏截图不能代替正式桌面验收。

本轮设计预览不证明生产集成、数据完整性、采集效率或发布已经完成。纯 UI 重构不应为了形式启动全市场采集；若实施确实修改采集/解析行为，再按现有开发指南做相应专项与有界实采验收。
