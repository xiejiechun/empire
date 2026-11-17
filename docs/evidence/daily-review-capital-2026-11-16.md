# 每日复盘资金流向：接入与验收

## 范围和现有工作

用户要求资金流向已有数据接入，缺少的显示“缺少数据来源”。在既有整体行情版本上继续，仅修改market_review只读查询、每日复盘资金分支及对应测试/说明。工作区原有改动保留，起始清单build/review-capital-git-before-20261116.txt；不启动其他聊天或子代理，不修改业务表、共享Redis、采集计划或来源协议。

## 设计及数据边界

设计先记录于[真实行情契约](../daily-review-market.md)资金章节，然后实现。review.market同一只读一致性快照复用完整东方财富日榜，增加明盘与暗盘合计、个股含暗盘主力流入/流出各前5，金额保留Decimal、排序按精确SQL值及证券代码。没有正/负值的完整榜是已知空榜；缺头、缺成员、休市、未收盘与缺日历是未知，不填0、不回退其他日期或盘中Redis。

原图板块流入/流出、两日ETF净申赎没有正式数据来源，逐项保留缺值，不用个股榜或ETF成交额替代。原虚拟资金数值已删除，样例日资金也读取真实归档；其余四个虚拟分支、笔记和预案范围不变。个股排行收在按需展开区域，保留简单导图布局。

只有既有表的只读聚合和两次LIMIT 5排序，按日最多10000证券、每SQL限8秒；既有表主键已覆盖日期范围。不新增采集、schema、索引、Redis键或数据库维护，采集实采和结构迁移准入不适用。文档权威正文与两表读取说明同步；其他源表行为未变的逐功能说明在实际审阅中逐项登记。

## 验证与交付

- 本任务独立13348测试实例经release_test_preflight.py核对端口、身份、建库/读写/清理权限及Redis连通；日志build/review-capital-preflight-20261116.log。tests/integration/test_review_market.py完整文件6项通过，12.29秒，日志build/review-capital-sql-20261116.log。覆盖只读事务、零值、缺头/缺成员、正负方向、同金额稳定排序、前5截断、精确小数、前日巨额不串入当天及完整空榜。
- Ruff与TypeScript通过。隔离Vite构建和Electron专项通过，日志build/review-capital-ui-build-20261116.log、build/review-capital-ui-20261116.log；结果desktop/qa-output/daily-review.json。验证明盘0、涨幅小数乘100、板块/ETF逐项缺值、样例日不回退虚拟资金、已知空榜、换日清值、同日刷新失败保留、迟到回执、滚轮、笔记/预案、明暗主题和1000px窄窗。无后端写命令；隔离截图daily-review-capital.png不当作真实桌面证据。
- 生产只读快照核对11月13日5378只、7月31日5333只完整榜的资金合计及两方向前5，与同一事务内精简原值集合排序和合计对应；约0.61秒/0.59秒。11月15日休市、11月16日未收盘保留未知。11月13日明盘−60106110151元、暗盘−76719282204元，合计−136825392355元；流入首位600410.SH、流出首位300308.SZ。记录build/review-capital-production-20261116.json和同名log，仅保留统计与各前5，不长期保存完整成功响应。
- 开发期间发现同仓库采集项改名任务，保留其全部修改并暂停共享构建/桌面操作，未代改其代码或发送跨聊天消息。该任务随后完成正式门禁59b27faafcfb48c689fb9d9fa5ce1f0d和本机启动器构建，报告passed=true、kind=local-development-launcher、portable=false，352/5468项通过，其余5116项未测。逐字节核对当前1360个src、desktop/src/electron、sql、scripts及tests文件与该报告inputs.json相符，包含本次资金实现和SQL专项；据此复用同一份构建，不再次构建。352项是该报告自身成绩，本任务另行执行的6项没有拼入JUnit或报告，不称全量通过。
- 正常关闭旧窗口后，从C:/Windows/Temp以生产程序目录配置启动真实Runtime，执行build/review-capital-live-20261116.cjs通过；日志build/review-capital-live-20261116.log，结果desktop/qa-output/review-capital-live-20261116.json。核对三项资金精确元值、明暗盘关系、流入流出各前5代码/名称/金额/涨幅、四项板块/ETF缺值、刷新、休市清值、未收盘、样例日真实资金和其余四分支独立标记。可见桌面、明暗主题及1000px窄窗无横向溢出通过，页面脚本错误为空。实际截图desktop/qa-output/review-capital-live-real-20261116.png和review-capital-live-dark-20261116.png均已视觉检查。
- 验证客户端正常关闭后，经dist/EmpireDesktop/Empire.exe重新打开可见窗口；配置SHA256与关闭前一致，没有保存测试笔记、预案或采集配置。正常Runtime继续原有计划，不把整个启动过程称为无业务写入。产物依赖当前仓库，不代表独立分发验收。

功能交付已完成，后续开发记录仅做文档事实同步与验证，不重新构建。没有待补的已授权来源接入；板块资金与ETF净申赎仍缺少正式来源，按用户要求保留缺值，其余四个分支继续逐项完善。

最终显式审阅保留并行任务既有说明及例外，核对产品源码、逐功能正文均无新增未审变更后记录资金专项审阅。文档契约603篇、4130链接、73表通过；完整tests/test_documentation_contracts.py的5项通过，6.66秒，日志build/review-capital-doc-check-20261116.log和build/review-capital-final-docs-20261116.log。其余四个文档文件的既有共享构建成绩未重复计入本次5项。确认本任务13348实例身份且无其他客户连接后正常关闭，记录build/review-capital-mysql-shutdown-20261116.json；生产MySQL、共享Redis未重启。正式重开窗口PID45608可见。
