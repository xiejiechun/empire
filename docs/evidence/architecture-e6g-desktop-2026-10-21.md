# E6g 同包真实桌面与发布结案

2026-10-21，北京时间。正式 `dist/Empire/Empire.exe`，release `7e85c4e4db9f47bdbd5a137e731c7041`，干净构建提交 `7373f3888f7c19334277d79023b18cf6e9eee49a`。computer-use技能的sky实际观察和操作窗口21760706，正常关闭后从C:/Windows重开18616692，最后工作台保持可见。E6g组织迁移范围已验收；结案提交推送精确核实后进入F，整个优化未完成。

## 发布、配置与查询

唯一命令：设置自有 `EMPIRE_TEST_MYSQL_SETTINGS=build/architecture-evolution-20261019/mysql-settings.json` 后运行 `./verify-release.ps1`，自然exit0，publication committed/passed。[证据审计](architecture-e6g-release-audit-2026-10-21.json)重新核对1794输入、54保留输出、24步骤。3844 passed、5原state-unit显式opt-in skipped、20 warnings，2616.54秒；跳过原因逐项保留，未计为通过。环境、42依赖、文档/数据库设计、架构/装配、Ruff、既定strict八文件、完整隔离集成、容量绑定、四档DPI、构建、中文空格搬移/配置smoke及切换通过。第22步模板生成的预期exit1不是门禁失败。既有Qt QML/tzdata及未用数据库driver打包警告保留。

完整源输入SHA `b64faadaaa99586189c014104bb2ab0fc6d437027fbd6ec706dfa62e10a70659`；EXE `5d34639af1bf256c039ee9859b975120038e4210f511e6af697ad88e8ac8d6e7`；安装树 `1399f679e8236114b7f19b858e436dff5e84ea6f4cbcf58ba846005d547a51fc`。发布全过程正式输入及HEAD冻结，未改release_lock或性能工具/协议/阈值。

实际命令 `py out/audit_release.py <release> <commit>` exit0；`py out/check_published_runtime.py --run <release> --report out/<新报告>` 的[发布后](architecture-e6g-post-release-2026-10-21.json)、[正常关后](architecture-e6g-post-close-2026-10-21.json)、[重开后](architecture-e6g-post-reopen-2026-10-21.json)均exit0。py指项目.venv/Scripts/python.exe，out指build/architecture-e6g-20261021。包内doctor从C:/Windows执行，真实Redis/MySQL连接；冻结源码的正式七kind query API使用安装配置，以limit3完整分页、每条引用、全部市场/空态和missing引用逐列与只读SQL一致。源码API、包内doctor、可见GUI分别举证，不冒称包内查询CLI。

两config原字节、48条app_setting的payload及updated_at、原插件偏好字节保持。插件验收展开偏好为159项；全部恢复true并正常关后，核实与原10项显式偏好等价，按实际当前SHA守卫独占备份，再恢复原字节，restore_test_preferences.py退出0。未覆盖config、保存测试任务计划或改日常代理策略。各只读快照pending0，生产日常计划仍可自然运行。

## U1～U3 实际桌面

[原始观察](architecture-e6g-desktop-observations-2026-10-21.jsonl)保存实际时间、窗口、完整UI树和截图元数据；截图于操作时直接审视。[导出清单](architecture-e6g-closure-export-2026-10-21.json)绑定原件和导出SHA，省略成功代表SQL行，未复制成功来源响应全文。

| ID/范围 | 实际操作与结果 |
| --- | --- |
| U3身份与导航 | 运行状态显示0.1.0/7373f3888f7c/干净提交，Redis/MySQL及归档启用；目录七项均按需打开。工作台45任务、活动0、原失败2、pending0；七规则原计划启动后约11:46自然完成，未修改策略 |
| U2涨跌幅/数量 | limit14条、科创板20%和主板10%、2026-07-06生效及上交所6.6正文可读；lot14条，主板最低100股、零股说明及3.3.8正文可读；未知终止日仍未明确 |
| U2时段/卖出/报价 | sessions23条，北交所及深交所2.3.2原文与14:57～15:00、09:30～11:30、13:00～14:57北京时间可见；settlement5条显示买入当日不得卖出/回转除外原文，未补造数值T+1；tick5条0.01元及深交所3.3.11可读 |
| U2税费 | stamp4条，2023-08-28起卖方0.05%、旧0.1%终止2023-08-27、买方0%，减半公告可读；transfer12条，2022-04-29起0.001%，最低收费未明确，新华社转述中国结算公告身份清楚，未冒充当前完整费率表 |
| U2空态/分页 | limit选CN并点查询实际0条，详情清空、翻页禁用；真实每kind不足200条，GUI下一页禁用合理。真实limit3完整分页另由正式API核对 |
| U2刷新/滚动 | sessions横纵滚动后选择深圳13:00～14:57，查询/刷新等异步完成，选择、两轴滚动及深交所引用正文保持 |
| U2窄窗 | 实际最外角拖至982×892，transfer筛选/查询/管理/分页及正文可读，表格横滚可用；首轮内角未改尺寸，不算通过 |
| U1独立生命周期 | 单停limit UI，采集/查询保持启用，目录搜涨跌幅无结果；再单停collector，任务/历史继续可用，立即采集明确拒绝“该采集插件当前未启用”。恢复UI而collector仍停，目录入口返回且正式显示14条。最后UI和collector均恢复 |
| U1共享保护 | 共享HTTP直接停用被拒绝，列出collector.rule_sources及其他collector/collection.control依赖；服务仍启用，未级联停用 |
| U2草稿/滚轮 | limit任务重试2改3未保存，后台刷新/切运行记录返回仍3；实际在数字框上滚轮值仍3。撤销回2，保存/撤销禁用；259200秒及代理优先可回退策略未改 |
| U2帮助 | 搜交易规则，真实正文说明七入口、保存/生效、来源与日期/单位、未知值和准备失败；系统架构显示features/trading_rules及remaining退役，公共路径唯一 |
| U3正常关开 | Alt+F4显示保存进度/结束归档/关闭连接；fresh窗口列表无Empire且无活动线程。原偏好恢复及关后只读核验通过。同EXE从C:/Windows重开18616692，1322宽工作台可见，本地连接、45任务/活动0/既有失败2/pending0 |

## 中间失败、资源与限制

UI树与截图在异步动作后偶尔慢一拍，均用后续纯观察确认，未将“正在查询/读取依据/执行”算完成。一次分类弹窗的UIA坐标命中Empire自有弹窗被工具拒绝，激活并fresh截图后按可见菜单恢复；一次type_text未产生筛选，后用set_value并核对结果。扩宽拖拽被工具因端点超出当前窗口边界拒绝，未改变应用；随后最大化完成草稿滚轮测试，重启回1322宽。一次只读JSON查看未指定UTF-8而编码错误，改显式UTF-8后读取成功；均无数据副作用。

[收尾资源只读](architecture-e6g-close-resource-2026-10-21.json) `py out/close_resource.py <release> <commit>` exit0：自有13348实际UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、原datadir，仅四系统库/无其他客户；生产UUID不同，冻结文件未变，pending0。实例继续供F，不停共享服务、不删业务数据或未解决错误、不删他人锁。

沪深T+1数值依据、科创板递增数量生效依据、北交所涨跌价格舍入、现行完整中国结算费率/最低收费仍缺，来源全链路通过不等于全部用途准备通过。北交所43号大宗报价10月26日生效不改变普通竞价、不启用暂缓盘后。H3空名债券、E4严格来源和资本历史准备限制保留。规则按文件组采集，随机30股不适用；本轮七kind/77参数、15全代理完整集合及内容证据见[开发记录](architecture-e6g-2026-10-21.md)。

结案文档验证：py -m pytest tests/test_documentation_contracts.py tests/test_documentation_review.py tests/test_documentation_sources.py tests/test_storage_help.py tests/test_rule_documents.py --basetemp build/pytest-e6g-docs-closure --junitxml out/docs-closure.xml -q，exit0，49 passed/33.67秒。最后documentation_contract review/check与verify_documentation均exit0（260文/1820链接/55表），git diff --check通过；纯事实文档结案不重打包、不改变上述发布身份。
