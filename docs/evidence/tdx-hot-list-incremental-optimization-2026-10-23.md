# 龙虎榜分层回查实施记录

用户2026-10-23授权先写实施文案并开发，见[方案](../tdx-hot-list-incremental-optimization.md)。本次是主动优化，无待修复生产错误ID，不清现有34条网络/来源样本。

新增纯函数review_due，以SHA-256(完整证券代码:日期)对7/30取模，比较本轮北京时间日期序数。缺少SQL头/pending先补，近7日每天、第8～90日7组、旧source_empty/partial30组；旧present显式范围重查。断点review_policy=2和固定through防止跨日或旧策略混用。普通/强制/显式范围沿用唯一execute路径；表、内容摘要与版本、统一归档和不变零DML不改。

现有SQL集合请求计划rotation-request-estimate.json：5580目录；旧10798详情，新994详情（present727/source_empty266/partial1），合计16378→6574，减少59.86%。新日期/重试另计，不能据此推断整轮耗时。

37解析/生命周期/轮转专项通过；5私有SQL/Redis归档测试通过。登记/结构/UI检查中发现装配说明仍旧，已同步准确声明，相关检查恢复通过。数据库设计契约与原容量证据仍有效。直接对旧无类型collector执行mypy会产生既有非范围类型错误；正式仓库mypy的13个已登记文件及新增review.py独立严格检查均通过，未放宽规则。

source-rotation-1/2因正式EXE仍运行，被单实例拒绝，私有资源未遗留。正常关闭EXE保留新增量断点后，source-rotation-3完成34股1322日期全链路及增量39响应（34目录+5详情），队列0，清理通过；但并行生成帮助改变源输入摘要，报告按规则FAIL，不作为正式实采证据。最终source-rotation-final-4.json已通过，源摘要f12743d046c93d031ddffa745250874dbe9f9d13cb148e15155e09c98510ec45与结束后输入匹配。seed20261023，从5580池随机30股加固定601139.SH/000001.SZ/000063.SZ/600198.SH，共34股1322日期；1395成功响应、1396实际代理请求（一次重试），无直连或回退。增量实际34目录+5详情=39响应，选择集合摘要32537d6522320e6ec191a12012af90b43e04a46c17d3d987f13859c49e8e4eb5；正式查询集合/内容一致，待归档0，私有SQL/Redis/锁/连接全部清理。

旧初始化已独立完成并通过全量只读审计（5580证券、208847日期），见[完成摘要](tdx-hot-list-initialization-complete-2026-10-23.json)。用户随后启动的旧规则增量8eaf2c062b594e32936fb84e71b43ac6仍保留断点；最终实采后先让旧EXE继续完成这轮，再发布新实现。正式发布及桌面验证尚未完成，不宣称优化已部署。

15:02通过旧正式EXE的继续采集恢复原batch8eaf2c062b594e32936fb84e71b43ac6，run0501e37290794c0fac89f9ec5417de7f。resume-rotation-old.json确认running/fetch/index575/pages5073，SQL随后确认5079页；分时快照队列2。每日19:30和代理优先不变。现有错误35条，新增登记0887874089f74635872be83433d4c613为14:19:14代理暂时故障，原轮已继续，不按程序修复清理。

## 正式发布与最终验收

旧规则增量batch8eaf2c062b594e32936fb84e71b43ac6于16:14:18完成5580证券、21959发布页，SQL/归档一致且队列0（rotation-heartbeat-20261023-1617.json）。首次发布3a7f5865aca145e2a317a4c01ca35234被架构门禁拒绝：review新模块归属漏登；仅补docs/architecture-contract.json的collector_support登记，提交78202a8，无源码及实采输入变化。

正式release4170d10374474b4c9aa960d99554f6ad通过并切换，提交78202a88bf4a852cccdb68d2258974239dd22688，4133 passed/5既有显式opt-in隔离演练skipped/20 warnings，测试2565.24秒；跳过项不算通过。架构、装配、文档、数据库设计、ruff/mypy、容量门禁、各缩放UI及打包/中文空格搬移smoke均通过，config由正式发布机制保留。正式manifest与EXE摘要已核对。

新EXE可见重开，真实龙虎榜任务页面显示7/30日轮转回查及每日19:30，旧完成状态保留。rotation-post-release.json确认配置代理优先/允许回退、无活动龙虎榜任务、queue0；production-rotation-query.json正式查询600198.SH/2024-09-25的4原因30席位内容核对通过，partial原样保留。rotation-desktop-acceptance.json记录同包桌面与身份。未额外运行生产全市场新策略轮次，34股增量39响应为严格代理实测，16378→6574仍仅当前SQL集合计划量；新策略由后续正常计划执行。

自有测试13348核实UUID、目录及其他客户端0后正常SQL SHUTDOWN，shutdown-rotation.json确认端口关闭，生产3307与共享Redis未动。37条网络/来源样本保留，无本次错误ID清理。实施及正式部署收尾完成。
