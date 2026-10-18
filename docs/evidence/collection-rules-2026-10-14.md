# 采集规则交付记录（2026-10-14）

目标：在采集任务运行详情、任务配置旁增加只读采集规则，并对全部当前及未来任务制定登记规范。

开工：共享工作区已有大量源码、文档和证据变更，保留原变更，不混入提交；同项目其他聊天未发现活动开发。当前桌面运行中，发布前按既有授权正常关闭，结束后重开；不重启Redis/MySQL、不清除待归档数据。

实现：43项正式任务，真实接口/参数、初始化/增量、市场与起止范围、恢复、Redis Stream/Hash/摘要、正式dataset及SQL表；复用已关联来源说明。资源随包发布。规范及AGENTS、采集开发指南、操作说明和覆盖登记同步。新增正式门禁验证覆盖、必填项和登记一致性，缺失规则拒绝发布。

验证：采集规则与任务UI45项通过；文档审阅与规则相关28项通过；全部43规则离屏渲染，参数表及520像素宽阅读已检查。离屏截图仅布局证据。

业务验收适用性：此次为只读规则与文档准入，不新增或修改采集/业务数据集，不需要迁移、实采或重做全市场完整性验收。没有按错误记录修复，不清除错误ID；实际采集完成范围不由规则说明推断。

正式发布：统一发布门禁通过，2483 passed、5 skipped、2 warnings。5项跳过均为需要显式开启的隔离演练（tests/integration/test_state_unit_isolated.py）；2项警告为既有QMouseEvent弃用提示。依赖、文档、结构设计、ruff、mypy、容量、四档DPI、打包及便携配置冒烟通过。完整日志为 build/collection-rules-release-private.log，报告为 build/release-report.json。

测试环境：首次门禁因业务账号缺少CREATE DATABASE权限（1044）中止；未提升业务账号权限，改用独立测试MySQL 13331及 build/index-prices-mysql/data 完成门禁。结束后核实目录及无其他连接，通过SQL SHUTDOWN正常关闭并确认端口关闭；生产MySQL 3307和共享Redis未重启。

发布文件：dist/Empire/Empire.exe 的SHA-256为 3a8a6c814543e9f8457a7dec35114e9cbff9d0875ba03fafa838ec12a7346eb6；规则JSON已入包并与源码一致。原 dist/Empire/config.toml 重建前后SHA-256均为 5C1E32FDF651B948C387106D2A006BA390B7CB1001827FC537262DEAE832F92F。

真实桌面：新EXE从C:/Windows工作目录启动并保持打开；显示本地服务已连接，真实业务查询及43项任务加载成功。采集任务中运行详情、任务配置、采集规则三个页签可见；股票回购规则的来源URL、GET参数表、章节选择及Redis/MySQL去向已核对，显示实际命名空间 empire:dev、数据库 empire、stock_repurchase_plan、collection_state 与对应断点和摘要位置。未修改或保存任务配置，未将既有任务失败状态当作本次已修复问题。
