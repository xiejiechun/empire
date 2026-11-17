# 整体行情真实接入：交付与验收

## 实现与范围

按用户2026-11-16要求，将每日复盘“整体行情”接入真实数据，缺失字段显示“缺少数据来源”。仅使用既有MySQL事实；没有新增采集、表、Redis键或业务写入。实现契约见[整体行情设计](../daily-review-market.md)。工作区原有大量改动已保留，起始清单为build/daily-review-real-market-git-before.txt。

桥接review.market使用严格合法日期校验和白名单调度，进入既有market.review.query的同一只读事务。原范围查询的读取与连续板计算提取到reading.py共享，新路径跳过无关题材。页面按日期/生命周期取消和丢弃旧回执；刷新失败保留同日结果，换日期清除旧值；旧虚拟整体行情字段已删除。其他五分支仍只在固定样例日展示独立标记的虚拟内容，不向其他日期复制。

## 已通过的开发验证

- 现行Ruff范围内相关源码与测试通过；项目配置的Mypy（12个文件）、TypeScript、隔离Vite构建通过。额外手动将严格Mypy扩展到旧有未类型化模块曾报54处注解错误，该范围不属于现行Mypy门禁；没有将其记为通过或放宽检查。日志分别为build/review-market-static-20261116.log与build/review-market-configured-static-20261116.log。
- 五个完整专项/集成文件共26项通过：test_headless_pages、test_market_review、test_desktop_bridge、integration/test_market_review_query、integration/test_review_market。日志build/review-market-delivery-tests-20261116.log。SQL使用本任务独立13348实例和每例UUID数据库，预检端口、独立身份、建读写清理权限及Redis连通通过。覆盖只读快照、Decimal精度、真实零值、样本差异、缺金额、池/资金榜头与成员不一致、连续板不采用N天M板标签、同指数不混用代码、休市/未来/未收盘及缺日历/缺前日基准。
- 隔离Electron界面专项通过，覆盖真实字段、缺北证/外围、迟到回执、同日刷新失败、跨日清值、默认今日/跨时区、草稿/持久化失败、滚轮、明暗主题和1000px窄窗。没有写命令；结果desktop/qa-output/daily-review.json，日志build/review-market-ui-qa-20261116.log。
- 生产库只读一致性快照调用正式read_market：11月13日38涨停、34跌停、31首板、7连板，成交额1667073597654.70元、资金−136825392355元、资金榜5378只；无完整性警告，约0.30秒。11月16日查询时为未收盘，返回pending和缺值；11月15日为休市。7月31日真实值100/0、90首板、10连板、成交额2559202881035.70元，约1.04秒。证据build/review-market-production-20261116.json及同名log；并非当日收盘已采齐证明。
- 将上述真实SQL结果回放到隔离Electron页面，核对11月13日精确字段及缺值显示通过，未启动第二Runtime或归档器。截图desktop/qa-output/review-market-real-20261116.png，日志build/review-market-proof-20261116.log；这是实际库结果的界面回放，不能称正式客户端桌面验收。
- 184篇帮助聚合生成通过；装配身份与语义登记检查通过。页面和七个既有业务表的读取覆盖已同步。

## 初始阻塞与解除

本轮期间共享仓库另一项远航指数开发持续新增src/empire/features/yuanhang_indices模块并修改sql/schema.sql。架构检查仍报告这些未分类模块；数据库设计检查报告DDL与正式字典尚不一致。日志build/review-market-architecture-20261116.log和build/review-market-database-gate-20261116.log。未修改或删除这些并行工作，也未代签其审阅。

上述情况属于初始开发阶段。随后并行指数任务完成结构、架构和覆盖登记，并将复盘读取迁移至正式yuanhang_index_daily_price。北证50使用899050，现已具有真实点位；外围五项仍显示“缺少数据来源”。并行任务自身交付见[远航指数记录](yuanhang-indices-delivery-20261116.md)，本记录不替代其来源验收。

## 已完成的正式交付

- 正式执行verify-release.ps1 -TestPlan build/review-market-test-plan-20261116.json，报告build/releases/4a6e17626eef4b81985cf6cfaad7faf9/report.json为passed=true；完整日志build/review-market-resume-release-20261116.log。11个完整文件共90/5452项（1.65%）全部通过，耗时171.05秒；其余5362项未测，不称全量通过。静态、依赖、文档、数据库设计、架构、装配、容量、前端、3项传输测试和本机启动器构建均通过；帮助185篇，文档601篇、4125链接、73表。门禁前核对当前源码与最新已通过发布的输入一致。
- 正常关闭客户端后完成正式构建，程序目录config.toml的构建前后SHA256一致。从C:/Windows/Temp以dist/EmpireDesktop/Empire.exe启动，使用原配置连接真实数据库，后端在线且读取55项任务；没有为本功能新增或修改生产结构、采集配置或业务数据。
- 真实Runtime桌面验证结果desktop/qa-output/review-market-live-20261116.json，日志build/review-market-live-20261116.log；帮助展示验证日志build/review-market-resume-help-20261116.log。首次默认2026-11-16，08:11尚未收盘，保留pending及缺值。切换11月13日，涨跌停、首板/连板、成交额、资金、涨跌家数和六个指数与正式只读查询逐项对应，其中北证50收盘876.331；外围五项显示指定缺值文案。刷新通过，11月15日休市清除旧值，不套用上一交易日。
- 固定样例日的整体行情同样读取真实归档，其余五分支独立标记虚拟内容；证券详情和笔记窗口可用，未保存测试笔记或预案。明暗主题、1160px窄窗口、今天按钮及可见桌面验证通过，页面脚本错误为空。实际截图：desktop/qa-output/review-market-live-real-20261116.png、review-market-live-today-20261116.png、review-market-live-dark-20261116.png；它们来自真实客户端，与前述SQL回放证据分别保留。
- 验证后正常关闭验收客户端，再经正式Empire.exe重开可见窗口。确认本任务13348测试MySQL无其他客户连接后正常关闭；没有重启生产MySQL或共享Redis。真实行情只读快照另存build/review-market-resume-production-20261116.json。

本轮交付已完成。产物为依赖当前仓库的Electron本机启动器，不代表独立分发验收；没有新增来源来补齐外围行情，也没有将虚拟分支宣称为真实功能。交付后的开发记录事实更新已核对源码及逐功能正文与既有审阅完全一致，保留原审阅说明与例外后记录本次审阅；文档契约通过（601篇、4126链接、73表），四个完整文档回归文件57项通过，耗时149.22秒。日志为build/review-market-final-doc-check-20261116.log和build/review-market-final-doc-tests-20261116.log；没有重新构建客户端。
