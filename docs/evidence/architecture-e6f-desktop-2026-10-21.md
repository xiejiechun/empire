# E6f 同包真实桌面与发布结案

2026-10-21，北京时间。正式 `dist/Empire/Empire.exe`，release `7f5acbb5a3e9412c9ff407e0978f4c80`，干净构建提交 `0c2ab3cca81329f13e904a9ff733f2f821abe3e9`。computer-use sky 实际观察和操作窗口6690612，正常关闭后从C:/Windows重开17699188，最后工作台保持可见。本文为本批组织迁移范围结案；E6g/F尚未实施。

## 发布、配置与正式查询

唯一命令：设置本轮自有 `EMPIRE_TEST_MYSQL_SETTINGS=build/architecture-evolution-20261019/mysql-settings.json` 后运行 `./verify-release.ps1`，自然exit0，publication committed/passed。[发布证据审计](architecture-e6f-release-audit-2026-10-21.json)重新核对1770输入、54保留输出和24步骤。3840 passed、5原state-unit显式opt-in skipped、20 warnings，2528.68秒；跳过原因逐项保留，未计入通过。环境、42依赖、文档/设计、架构/装配、Ruff、既定mypy8、完整隔离集成、容量绑定、四档布局、构建、中文空格搬移/配置smoke和正式切换通过。

源输入SHA `edcd8f14b2a6b52ed7ea365b52011f880714337270be940666cc40a6e8af710f`；EXE `309cc8a602cbf4a4099f74a11d215842bff7bac46bf9d40582cffda9372832b6`；安装树 `3d31fefbd77caf3a472e89f3b2ccfa6d874bbbd46f05b4f5f54b4bd0516a8c76`。Qt QML/tzdata及未用数据库driver的PyInstaller警告保留原日志，没有修改依赖掩盖。

`py out/check_published_runtime.py --run 7f5acbb5a3e9412c9ff407e0978f4c80 --report out/<新文件>`：[发布后](architecture-e6f-post-release-2026-10-21.json)、[正常关后第二轮](architecture-e6f-post-close-2026-10-21.json)、[重开后](architecture-e6f-post-reopen-2026-10-21.json)均exit0。包内doctor从C:/Windows执行，真实Redis/MySQL连接；冻结源码正式回购query API使用安装配置，首屏200、603312.SH三方案及301345.SZ两方案的完整分页和详情、日期/状态、空查询和missing detail逐列与只读SQL一致。源码API、包内doctor和可见GUI分别举证，不冒称包内查询CLI。

两config原字节、48条app_setting payload及updated_at、原插件偏好最终字节保持。成功只读快照pending0；日常任务可能继续运行，不把生产动态数据当作私有实采样本。`py`为`.venv/Scripts/python.exe`，`out`为`build/architecture-e6f-20261021`。

## U1～U3 实际桌面

[原始观察](architecture-e6f-desktop-observations-2026-10-21.jsonl)记录01～91的时间、窗口、完整UI树和截图元数据；截图在操作时直接审视。[导出清单](architecture-e6f-closure-export-2026-10-21.json)记录原件及脱敏导出SHA；未复制成功响应全集。

| ID/范围 | 实际操作和观察 |
| --- | --- |
| U3身份/按需创建 | 运行状态显示0.1.0/0c2ab3cca813/干净提交与服务连接，数据目录打开回购后真实读取200方案 |
| U2内容 | 西典新能603312.SH/方案16686/公告2026-10-21，计划25000000～50000000元、555500～1111100股，价格未知～45元/股；来源未提供的实际回购、完成日保持未知 |
| U2分页/筛选 | 下一页首拾比佰920768.BJ；该证券+起止2026-07-29+回购完成为一方案16352，计划10000000～20000000元、1000000～2000000股，实际1360000股/9535057.84元、6.9～7.12元/股；统计2026-08-25、公告2026-08-27、完成2026-08-25。999999.SH同范围为0且翻页禁用 |
| U2滚动/刷新 | 新页默认200表格向下滚后选择金海通603061.SH/16679，详情计划100000000～150000000元、285700～428600股；点击查询/刷新并等异步完成，滚动位置、选择及详情保持 |
| U1独立生命周期 | 单停回购UI，查询/collector仍启用，数据目录搜回购为0项。再单停collector，控制器/历史仍可用；立即采集明确拒绝“该采集插件当前未启用”。恢复UI而collector仍停时可查询200方案和详情；最后UI/collector全部恢复启用 |
| U1依赖保护 | 共享HTTP直接停用明确拒绝并列出回购及其他collector/collection.control依赖，服务仍启用；未执行级联停用 |
| U2草稿/滚轮 | 回购任务重试2改3不保存，经后台刷新、切运行记录再返回仍3；在数字框上滚轮未改值。撤销后2、保存/撤销禁用；网络和计划未保存修改 |
| U2窄窗/帮助 | 实际外角拖至982宽，筛选、管理、分页和正文可读，表格可横滚；帮助搜索回购显示操作、日期/单位/限制及本次features/repurchases、安全私有验证/全方案范围说明 |
| U3关开 | Alt+F4出现保存进度/结束归档/关闭连接提示；fresh窗口枚举无Empire、无仍有线程进程。原偏好恢复后关后只读通过。同EXE异cwd重开17699188，1322宽工作台可见，本地连接、45任务/活动0/既有失败2/pending0 |

## 失败、恢复与限制

[首次关后核验失败](architecture-e6f-post-close-preferences-failed-2026-10-21.json)如实保留：插件开关将原10项偏好展开为159个默认启用项，config不变但偏好字节不同。首次本地恢复脚本因未安装psutil退出1，未修改文件；使用现有PowerShell进程核查方式修正本地脚本，不安装依赖或改发布代码。正常关后核实全部159项true、原10项显式偏好等价，hash守卫核对并独占备份展开文件，再恢复原字节，退出0。随后post-close-2与post-reopen-1真实核验通过。失败报告没有改写为通过。

首次分页工具要求刷新window state；刷新时其他应用遮挡，激活Empire并重新观察后恢复。第一次内角拖拽未改变尺寸，实际最外角拖后得到982宽。UI树与截图异步切换不一致时取下一次纯观察确认最终状态。上述中间状态不计通过。

[收尾资源只读核查](architecture-e6f-close-resource-2026-10-21.json)exit0：自有13348实际UUID `a3e8a5eb-cb64-11f1-8ddf-380525361d4e`、原datadir保持，仅四系统库、无其他客户会话；生产UUID不同，冻结文件未改，pending0。实例运行供下一批；生产库/共享Redis未关闭或清理，未删他人锁、业务数据或未解决错误。

本批五模块组织等价；全市场5586方案/2963证券、12全代理全链路内容核对已完成，不宣称随机30股或严格历史回放通过。T3首两轮尖峰失败及原因未知保留；第三轮完整18项通过。历史H3空名债券、E4严格来源和资本历史准备限制保持。结案提交推送并精确核实后才进入E6g；整个优化未完成。
