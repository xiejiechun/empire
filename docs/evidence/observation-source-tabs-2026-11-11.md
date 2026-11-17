# 观察日历来源窗口重设计

用户要求改善来源说明样式，使用Tabs并明确数据来自哪张表。本轮以居中详情窗口替换原Popover，六标签分别展示指数、成交、两融、汇率、日历和当月覆盖。统一来源标题、采集任务卡、MySQL业务表、数据粒度、字段映射表及读取口径；有独立正文滚动和关闭入口，窄屏、明暗主题适配。来源映射逐项核对正式查询及schema.sql，尤其区分source_total存储列与total_balance查询别名、stock_index辅助目录与行情事实、fx_price_year覆盖表与fx_daily_price收盘。

开工保留共享工作区已有修改和未跟踪文件；未启动子代理、发送其他聊天消息或修改其他业务。本轮仅前端展示及说明，不改查询、采集、计算、业务表、Redis键或保存偏好，无数据库结构设计/迁移、采集实采及数据库字典改造需求。实现前方案已更新docs/observation-calendar-plan.md。验证与正式发布结果完成后补记，未执行不记为通过。

## 发布前验证

- TypeScript与隔离前端构建通过，日志build/observation-source-tabs-ui-build-20261111.log。
- 既有观察交互QA通过；补充六标签逐项切换、五类真实表名及关键字段、当月覆盖、窗口关闭、暗色和760px窄屏窗口不越界验证。日志build/observation-source-tabs-qa-20261111.log，截图desktop/qa-output/observation-data-sources.png、observation-sources-dark.png、observation-sources-narrow.png已逐张检查。
- 文档权威正文、聚合及显式审阅和文档契约通过，日志build/observation-source-tabs-doc-generate-20261111.log、observation-source-tabs-doc-review-20261111.log、observation-source-tabs-documentation-20261111.log。
- 自有13348独立测试实例正常初始化，端口/身份及建库读写清理、Redis预检通过。未改生产MySQL或共享Redis。正式测试选择四个文档文件和观察查询回归文件，保持正式入口自带静态、容量、前端和传输门禁；不重复无改动的FX采集或全项目来源验收。

## 正式发布与真实桌面

- 正式门禁e6fcd31c416743f8a4ccf77546ffc8c0通过，72/5350项执行通过、5278项未测；静态、文档/设计/架构/装配、容量、前端及传输检查通过。日志build/observation-source-tabs-release-20261111.log，正式report.json位于该轮build/releases目录；为依赖仓库的local-development-launcher、portable=false，不宣称全量或独立分发验收。
- 正常关闭Empire并等待进程退出后构建，从TEMP工作目录启动正式dist/EmpireDesktop/Empire.exe。根目录与程序目录config.toml哈希均与构建前相同；独占测试MySQL按端口和datadir核对归属、确认无外部连接后正常SHUTDOWN，端口已关闭，证据build/observation-source-tabs-mysql-shutdown-20261111.json。未强杀进程、删除锁、关闭共享服务或手动采集。
- 13:49起实际可见Electron桌面读取2026-11月历成功，逐项切换六个来源标签，核对指数/成交/两融/汇率/日历真实表与字段、source_total优先及total_balance派生说明、偿还比公式和当月5574～5578只Top样本限制。长两融内容可在正文滚动，标签与关闭区保留；Esc关闭恢复月历，重新打开默认指数标签。窗口最后保留新版来源详情供用户查看，未改保存视图或任务设置。
- DataSources.tsx、sourceDefinitions.ts及dataSources.css逐文件哈希与正式发布输入快照一致。实际桌面检查单列，不改门禁报告的“not verified by this gate”。本项无未完成内容；业务数据覆盖由原采集任务负责。
