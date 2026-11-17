# 采集任务显示名称统一

2026-11-16，按用户授权调整全部56项采集任务（含已归档项）的显示名称，其中49项改名。平台仍由原平台分组和来源属性展示；“同花顺行业”按用户指定保留。任务ID、归属、来源、默认计划、已保存计划、断点、数据集、查询、网络和归档行为均不变，无数据库维护。

## 正式实现与验证

直接维护各业务 TaskContribution.name 和对应 PageContribution.title；不引入运行时命名兼容层。装配不可变基线保留，已有任务和页面逐项记录精确旧新名称；新增功能登记只同步自身名称。专项回归确保名称批准不能放行来源、计划和其他语义变化。正式门禁采用相关完整测试文件，构建后核对真实桌面与配置保留；本次不改变采集协议，无需重做来源实采。

容量报告仅因显示元数据绑定变化的，指数及涨跌停离线隔离重测。分红旧测量工具会重取全报告期，故保留旧报告与其SHA不动，以 docs/capacity-display-names.json 登记原始源文件副本：副本SHA必须吻合原报告，完整AST只允许 TaskContribution 第二参数从纯 item[0] 加平台后缀变为 item[0]，其他节点完全相同。设计、原始副本、专项反例必须同时存在；实际采集、计划、来源、存储或副作用变更仍须重新测量，不可复用。

## 名称清单

|任务ID|原名称|现名称|平台分组|
|---|---|---|---|
|ths-fx-live|同花顺汇率实时行情|汇率实时行情|同花顺远航版|
|ths-fx-daily|同花顺汇率历史日线|汇率历史日线|同花顺远航版|
|eastmoney-graymarket|明盘暗盘资金榜（东方财富）|明盘暗盘资金榜|东方财富|
|sina-news|新浪 7×24 小时全球实时财经新闻直播|7×24 小时全球实时财经新闻直播|新浪财经|
|ths-holders|股东研究（同花顺）|股东研究|同花顺|
|ths-income|利润表（同花顺）|利润表|同花顺|
|ths-balance|资产负债表（同花顺）|资产负债表|同花顺|
|ths-cashflow|现金流量表（同花顺）|现金流量表|同花顺|
|ths-industries|同花顺当前行业|同花顺行业|同花顺|
|ths-stocks|同花顺 A 股股票列表|A股股票列表|同花顺|
|sina-stocks|新浪 A 股股票列表|A股股票列表|新浪财经|
|cninfo-calendar|大 A 交易日期（巨潮资讯）|A股交易日历|巨潮资讯|
|tdx-suspensions|沪深 A 股历史停复牌（通达信）|沪深 A 股历史停复牌|通达信|
|tdx-dividends|分红送转（通达信）|分红送转|通达信|
|tdx-additional-issues|增发（通达信）|增发|通达信|
|tdx-rights-issues|配股（通达信）|配股|通达信|
|ths-capital|公司资本运作（同花顺）|公司资本运作|同花顺|
|ths-listings|股票上市与发行资料（同花顺）|股票上市与发行资料|同花顺|
|tdx-listing-status|暂停恢复终止上市（通达信）|暂停恢复终止上市|通达信|
|tdx-company-renames|公司更名（通达信）|公司更名|通达信|
|tdx-security-renames|股票更名（通达信）|股票更名|通达信|
|tdx-st-implementation|实施ST（通达信）|实施ST|通达信|
|tdx-st-removal|撤销ST（通达信）|撤销ST|通达信|
|tdx-unlocks|大小非解禁个股与明细（通达信）|大小非解禁个股与明细|通达信|
|tdx-unlock-industries|大小非解禁行业（通达信）|大小非解禁行业|通达信|
|tdx-earnings-forecast|业绩预告（通达信）|业绩预告|通达信|
|tdx-earnings-quick|业绩快报（通达信）|业绩快报|通达信|
|tdx-earnings-disclosure|业绩披露时间（通达信）|业绩披露时间|通达信|
|tdx-earnings-report|业绩报告（通达信）|业绩报告|通达信|
|tdx-holder-count|股东户数（通达信）|股东户数|通达信|
|tdx-shareholder-changes|重要股东持股变动（通达信）|重要股东持股变动|通达信|
|eastmoney-repurchases|股票回购（东方财富）|股票回购|东方财富|
|rules-limit-rules|涨跌幅规则记录|涨跌幅规则记录|官方规则|
|rules-settlement-rules|买入后何时能卖的规则|买入后何时能卖的规则|官方规则|
|rules-lot-rules|最小买卖数量规则|最小买卖数量规则|官方规则|
|rules-tick-rules|最小价格变动规则|最小价格变动规则|官方规则|
|rules-sessions|交易时段规则|交易时段规则|官方规则|
|rules-stamp-duty|印花税税率记录|印花税税率记录|官方规则|
|rules-transfer-fee|过户费收费记录|过户费收费记录|官方规则|
|kaipanla-themes|题材列表与日内变化（开盘啦）|题材列表与日内变化|开盘啦|
|kaipanla-theme-details|题材最新详情（开盘啦）|题材最新详情|开盘啦|
|ths-yuanhang-prices|远航版完整历史日线|股票完整历史日K|同花顺远航版|
|ths-yuanhang-financial|远航版权息与股本历史|权息与股本历史|同花顺远航版|
|ths-yuanhang-indices|同花顺远航版 A股指数|A股指数|同花顺远航版|
|ths-yuanhang-index-members|同花顺 指数成分|指数成分|同花顺|
|ths-yuanhang-index-prices|同花顺远航版 指数日K|指数日K|同花顺远航版|
|ths-yuanhang-limit-up-pool|远航版涨停板|涨停板|同花顺远航版|
|ths-yuanhang-sprint-limit-up|远航版涨停冲刺|涨停冲刺|同花顺远航版|
|ths-yuanhang-connect-broad-pool|远航版连板池|连板池|同花顺远航版|
|ths-yuanhang-open-limit-up-pool|远航版炸板池|炸板池|同花顺远航版|
|ths-yuanhang-limit-down-pool|远航版跌停板|跌停板|同花顺远航版|
|ths-yuanhang-reason|远航版历史涨跌停原因|历史涨跌停原因|同花顺远航版|
|tdx-hot-list|个股龙虎榜（通达信）|个股龙虎榜|通达信|
|ths-market-margin|市场融资融券（同花顺）|市场融资融券|同花顺|
|tdx-industry-margin|行业融资融券（通达信）|行业融资融券|通达信|
|tdx-margin|个股融资融券（通达信）|个股融资融券|通达信|
