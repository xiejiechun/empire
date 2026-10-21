# F 修复包发布与真实桌面结案

F组织治理及帮助树修复的适用发布、同包真实桌面和资源恢复已验收。源头严格实采的历史失败保持独立结论，见[最终逐项报告](architecture-final-2026-10-21.md)。本记录为发布后的事实文档，不改变已发布EXE身份。

## 同一发布身份

| 对象 | 实际身份 |
| --- | --- |
| 正式实现 | `280a7da912a06cd522f2ea407eee4a816bad4703`，main，冻结时dirty=false；含F实现`f2fbe995ab4c975808b42769fe26e50f849f2f43` |
| 唯一正式入口 | `./verify-release.ps1`，显式私有13348测试配置，session3338自然exit0 |
| release / journal | `4f8f55d07a274ad4adfe78a34f815076`；`build/releases/4f8f55d07a274ad4adfe78a34f815076/publication.json` committed/passed |
| 完整发布输入SHA-256 | `7592789ee3f327ab01aacb0739c206830b72f7d2250bddb0d8ecc85c0d3391d7` |
| EXE SHA-256 | `a309ff13cf67cc2e65cc17d60b6db6cd009e81f9f0b77a054a880bdfdf611408` |
| 安装树SHA-256 | `9c1a1622487c57c5a602605f37ebe7ad6428d76adcadd2c8d8bf0b89f58d7b21` |
| 完整pytest | 3972 passed、5 skipped、20 warnings；2467.25秒 |

五个跳过为原`tests.integration.test_state_unit_isolated`显式opt-in演练，名称和原因完整保留在[发布审计](architecture-f-release-audit-2026-10-21.json)，不计通过。25步骤、1978输入、58保留输出已逐项核对；首次配置模板生成的预期非零步骤按原结果保留。冻结工具、协议、基线、阈值和release_lock没有为本轮改动。

实际命令`.venv/Scripts/python.exe build/architecture-f-20261021/audit_repair_release.py 4f8f55d07a274ad4adfe78a34f815076 280a7da912a06cd522f2ea407eee4a816bad4703`退出0。审计中`actual_desktop=in_progress_separate_observations`保持原值；桌面由下面的实际操作独立证明。

## 配置、正式查询与用户设置

三次运行`.venv/Scripts/python.exe build/architecture-f-20261021/check_published_runtime.py --run 4f8f55d07a274ad4adfe78a34f815076 --report <本轮独占路径>`均exit0：

| 本地报告 / UTC时间 | 正式导出 | 实际范围 |
| --- | --- | --- |
| post-release-repair-1.json / 07:12:07 | [发布后报告](architecture-f-post-release-2026-10-21.json) | 同包manifest/EXE/tree、异cwd doctor、查询、配置及设置前像 |
| post-close-repair.json / 07:40:16 | [正常关后报告](architecture-f-post-close-2026-10-21.json) | 原偏好字节恢复后复核全部相同范围 |
| post-reopen-repair.json / 07:41:29 | [重开后报告](architecture-f-post-reopen-2026-10-21.json) | 同包重开后再次核实，query服务正常回收，global pending0 |

`<本轮独占路径>`分别为`build/architecture-f-20261021/`下表中三个实际文件；未覆盖旧报告。正式EXE在`C:/Windows`运行doctor，真实Redis/MySQL均connected、退出0。正式查询使用发布时冻结源码API和安装配置：股票前20项与SQL逐键/内容核对、当前目录及同连接366日截止契约、当月日历31天、新闻前20项；包内doctor与可见GUI另验，不将源码API冒充包内执行。新闻ID随正常日常计划更新，三次分别5157635、5157862、5157865，不称原子快照或历史全覆盖。

两份config原SHA均`5c1e32fdf651b948c387106d2a006ba390b7cb1001827fc537262deae832f92f`；原插件偏好SHA`8cbc58900b35bf4c8b2f9fff47ed95f67f6e20782734f38a0819ff3c7cadd63e`。验收开关恢复全启用后，正常关闭守卫下恢复原10条配置字节；扩展159项的验收后副本保留本地，未覆盖原备份。全部48行app_setting的payload及updated_at保持，摘要`9e59d702765610a9f91bfdfcc19bcfc104590d239bd87be6dfa99a95c511c1ac`。包内143主题与当前Article字段/聚合字节一致。机器报告的`actual_desktop=pending_separate_real_observations`原样保留。

## 可见桌面实际操作

2026-10-21北京时间15:13～15:41，真实`dist/Empire/Empire.exe`，窗口15009552；同包重开窗口4197432。操作工具为computer-use的`@oai/sky`；85条既有观察的时间、窗口、截图元数据及UIA摘要见[真实观察索引](architecture-f-desktop-observations-2026-10-21.json)。原始JSONL留本地build；公开导出排除业务正文，不另造图片或成功截图。以下为实际观察，非离屏推断。

| 编号 / 操作 | 观察结果与限制 |
| --- | --- |
| 修复反例 / 预热完整UIA树，连续折叠和展开多个分类 | 隐藏条目从可见行消失，操作和后续UIA均响应；未再出现首包卡死。首包失败未删除，见[修复记录](architecture-f-desktop-repair-2026-10-21.md) |
| M2/M3 / 搜索、章节、help链接、历史、空态 | “文档 分工”返回4结果；章节跳到正文维护位置；help链接打开数据库职责；返回/前进恢复文章和滚动；不存在关键词0结果且空态正确 |
| U2 / 帮助页面回收后重建 | 经过业务页、设置和插件页后，新HelpPage仍恢复“文档分工与更新”、滚动306及历史 |
| A4/U3 / 股票正式页 | 5579条、28页/200；选000008.SZ神州高铁后刷新保留身份及滚动；下一页实际显示201～400 |
| A4/U3 / 数据目录搜索新闻、打开正文 | 40548条，2026-10-21 15:24:43新闻可读；这是当时动态快照 |
| A4/U3 / 日历月份及日期明细 | 2026-10共31/31、17交易/14休市；10-21显示交易及内容变更时间2026-09-23 08:21 |
| U3 / 运行状态身份 | `Empire 0.1.0 · 280a7da912a0 · 干净提交`，真实本地服务连接，pending0 |
| U1 / 单停前十大股东UI | 对应查询和collector仍启用；恢复成功 |
| U1 / 单停股东研究collector并实际点继续采集 | 控制器、历史和其他任务继续可用；实际命令明确拒绝“该采集插件当前未启用，请先在插件管理中启用”；未执行该来源请求，随后恢复collector |
| U1 / 尝试直接停共享HTTP | `Stop dependent plugins first: ...`拒绝，共享服务保持启用；未点级联停用 |
| U2 / 草稿、后台刷新、重建、滚轮和撤销 | 实际重试基准30，草稿30→29未保存；刷新/切页重建仍29；滚轮不改；撤销回30，保存/撤销按钮禁用。没有把旧猜测2作为基准 |
| U2 / 真实窄窗 | 实际974px宽，帮助正文和表格换行可读；任务改上下布局，保存栏可用。首次边缘drag未调整；经Alt+Space→s→Right进入系统调整后成功。观察标签help-982-width是旧标签，实际尺寸以截图元数据为准 |
| 正常关开 | Alt+F4后首枚举仍有窗口，等待后07:39:54Z fresh枚举无Empire，另核无活动Empire；恢复偏好及关后查询后，从C:/Windows重开同一EXE |

最终真实工作台1322×892可见，45任务、活动0、既有失败3、pending0、本地服务已连接，窗口4197432保持打开。失败3为日常任务当时状态，没有清错让其变绿。只读取消、写命令不因切页取消等竞态由专项及完整门禁支持；不声称全部竞态均在桌面人工重现。

## 资源与剩余边界

`.venv/Scripts/python.exe build/architecture-f-20261021/stop_owned_mysql.py`退出0，[实际关闭报告](architecture-f-private-mysql-close-2026-10-21.json)记录UTC07:41:34.520429：核实际server_uuid `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、13348、原本轮datadir，仅四系统库/其他客户端0后执行正常SQL SHUTDOWN，端口关闭且目录保留。未强杀数据库、清共享Redis、删除业务数据或锁；生产3307继续使用。

F未实质修改采集/解析，随机30股本批不适用；持有人H3固定空名债券、E4严格来源失败及资本历史准备差异均保留。E5完整分红容量635期/58607来源行已完成。最小schema成本优化未采用、无配对收益测量，不称加速。

五份报告为原字节复制，桌面索引只做元数据投影；原文件及导出SHA见[证据索引](architecture-f-closure-evidence-index-2026-10-21.json)。结案文档审阅、回归与Git交付另见[最终逐项报告](architecture-final-2026-10-21.md)。
