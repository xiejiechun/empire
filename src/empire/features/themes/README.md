# 开盘啦题材

本业务包拥有列表/详情两个180秒任务、七日日内历史、两项统一归档数据集、五张结构化业务表与可搜索数据页面。上线验收尚在进行，实际发布以发布报告为准。使用方式见[题材说明](docs/help/overview.md)，设计见[实施方案](../../../../docs/kaipanla-theme-implementation.md)。

来源经共享下载器、代理、频控及资源预算执行。目录用游客TLS协议首次完整订阅响应；详情用匿名HTTP并剥离继承凭据。本机材料通过scripts/import_theme_guest_material.py显式导入程序config.toml，DPAPI保护，不依赖运行中的模拟器。证券市场先用正式目录和已归档题材身份，缺失才用新浪精确代码查询，不用关联的新代码替换来源旧代码。

日内每天一个基准，其余记录字段差异，保留今天及前六日；SQL首次/每小时/15:10后首轮归档日列表，详情只保留最新。主题材及子题材均保留，子题材热度/排名为NULL。根Stocks、同分类同证券多理由与相同关联出现次数全部保留。

初始化：先采列表，详情每轮最多32题材补齐，全部当前主题材已有完整详情才完成初始化。以后缺失/改名优先，超过24小时的详情分摊核验。下载和入队不逐题材等SQL，仅整轮入队后确认归档；Redis存活按断点恢复，Redis丢失依据SQL规划，丢失的日内轨迹不补造。

维护入口scripts/create_theme_schema.py预检，正常停机且队列为0时--apply；不自动DDL。入口与字段字典随docs/help登记，运行说明由统一文档构建生成。

专项：tests/test_theme_*.py；隔离集成：tests/integration/test_theme_history.py、test_theme_typed_storage.py、test_theme_archive.py。启用EMPIRE_INTEGRATION且指定专用EMPIRE_TEST_MYSQL_SETTINGS，框架每例创建UUID数据库/Redis namespace，仅清理自有数据。

随机种子20261024的30题材及军工通过真实代理全链路核对，252条目录SQL集合一致、待归档0，见[实采证据](../../../../docs/evidence/kaipanla-theme-formal-2026-10-24.json)。这是题材采样，不冒充30股票插件验收或全题材生产已采完。
