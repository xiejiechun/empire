# E6d 修复版同包真实桌面结案

2026-10-20 23:18～23:40，北京时间。实际操作正式 `dist/Empire/Empire.exe`，release `0cc06d1a846f42e78088bfad72ccfcd4`，干净构建提交 `7b1fb830273f928580a8d9596e0d120de418b96f`。通过 computer-use 的 sky 观察和操作可见窗口857908，正常退出后重开1514190。不是离屏测试。

## 身份和机器证据

- [完整发布审计](architecture-e6d-release-audit-guard-fix-2026-10-20.json)：24步骤、54留存输出、1715输入无失配；完整3823 passed、5原opt-in skipped、20 warnings，2584.38秒。publication committed/passed。
- [发布后只读核查](architecture-e6d-post-release-guard-fix-2026-10-20.json)和[正常关闭后核查](architecture-e6d-post-release-closed-guard-fix-2026-10-20.json)：包内doctor从C:/Windows执行，真实Redis/MySQL连通；正式查询集合、内容、关联和空态核对通过。查询API使用当前源码与安装配置，包内doctor和GUI独立列证，不把源码查询冒称包内查询。
- [111条原桌面观察](architecture-e6d-desktop-observations-guard-fix-2026-10-20.jsonl)、[导出与断言审计](architecture-e6d-final-evidence-audit-guard-fix-2026-10-20.json)、[重开补充更正和实际工作台](architecture-e6d-desktop-reopened-guard-fix-2026-10-20.jsonl)。补充文件逐字节复制，SHA256 `01cff9aa8cea0773ceade94d84f4c96a5e5acf21e42efcef4931c2c34f39052e`；原观察和原审计未改写。

## U1～U3 实际操作与结果

| 适用项 | 实际操作与结果 |
| --- | --- |
| U3 身份、入口和查询 | 运行状态显示Empire 0.1.0 · 7b1fb830273f · 干净提交，两服务启用、pending0、无契约隔离。数据目录打开两页；个股首屏和分页往返可用，相同条件刷新保留滚动位置 |
| U2 关联反例复验 | 600889.SH/2027-12返回6493500股，明细南京新工投资集团有限责任公司；改000000查询立即清明细，最终0条，旧明细不残留。开发组件另覆盖迟到结果所有权，真实桌面不伪称观察了确定性竞态 |
| U3 行业业务 | 首屏、第二页首条矿物制品·2027-12及返回首页；造纸/2028-08-01单月1条，110000股/2887500元，估值基准2026-10-19；不存在行业明确0条。数量/金额单位和比例正常 |
| U1 插件生命周期 | 两UI分别停用只移除自身页面，另一业务可用；两collector分别停用再恢复；两query单停分别因collector.tdx_unlock_industries/collector.tdx_unlocks依赖而拒绝，未级联停用；最终全部恢复 |
| U2 草稿与滚轮 | 行业任务取消勾选启用但不保存，切工作台返回及后台刷新后草稿保持；撤销恢复勾选，保存/撤销禁用。执行方式组合框滚轮保持每天定时，页面滚动正常 |
| U2 窄窗、帮助 | 实际981像素宽，行业筛选/数据/分页和个股空态/明细区正常；说明搜索解禁，两业务正文及明细清理/滚动说明可见 |
| U3 正常关开 | Alt+F4观察等待保存、归档、关连接提示，fresh窗口列表无Empire；同正式包重开1514190，实际再进工作台，45任务、活动1、既有失败2、pending0。最后1322宽工作台可见；这些是带时间的快照 |

## 设置、资源和操作偏差

[设置审计](architecture-e6d-settings-guard-fix-2026-10-20.json)核实全部48行SQL app_setting payload及updated_at相同，两config字节相同；验收插件恢复，偏好仅有完整registry展开及退役scheduler键删除，按guard核实后恢复原字节。45保存策略在before/closed/reopened完全相同，next_due允许日常推进。两config SHA256为`5c1e32fdf651b948c387106d2a006ba390b7cb1001827fc537262deae832f92f`；原偏好为`8cbc58900b35bf4c8b2f9fff47ed95f67f6e20782734f38a0819ff3c7cadd63e`。

操作偏差保留：点击滚动区外checkbox的UIA索引曾误触任务启动，界面显示任务已启动，行业日常采集自然完成（23:29:54/703行/pending0）；未改保存策略，不计入隔离实采证据。随后先滚入可见范围完成草稿验证。一次旧导航索引被工具拒绝，无操作，fresh后继续。重开首观察标签误写工作台，实际恢复旧债券持有人页；原记录保留，补充记录明确更正，再实际点击工作台核实。

[最终资源](architecture-e6d-final-resources-guard-fix-2026-10-20.json)：自有13348实际UUID/datadir保持，仅四系统库、无其他客户端，无本轮私有资源残留，继续运行供后续；生产3307和共享Redis未关闭、重启或清理，冻结文件字节保持。H3固定空名债券、E4严格来源失败、资本历史准备限制及旧错误未清。E6d组织迁移适用出口已验收，整个优化未完成；结案提交推送核实后才进入E6e。
