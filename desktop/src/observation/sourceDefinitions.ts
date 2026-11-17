export type DataSource = {
  key: string; label: string; provider: string; description: string; task: string; taskId: string;
  tables: { name: string; role: string }[]; grain: string; scope: string;
  rows: { metric: string; fields: string[]; method: string }[]; notes: string[];
  snapshot?: { task: string; taskId: string; key: string };
};

export const dataSources: DataSource[] = [
  {
    key: 'index', label: '指数行情', provider: '同花顺 · 指数日行情',
    description: '所选指数的收盘、量额及前一交易日涨跌幅。',
    task: '指数日K', taskId: 'ths-yuanhang-index-prices',
    tables: [{ name: 'yuanhang_index_daily_price', role: '日行情事实表' }, { name: 'yuanhang_index', role: '辅助目录：指数代码与名称' }],
    grain: '一个指数 × 一个交易日', scope: '按 index_code 及 trade_date 读取；使用页面当前选择的指数。',
    rows: [
      { metric: '指数收盘', fields: ['close'], method: '直接读取，单位为指数点。' },
      { metric: '指数涨跌幅', fields: ['close', 'trade_date'], method: '（当日收盘 ÷ 前一正式交易日收盘 − 1）× 100%。' },
      { metric: '指数成交额', fields: ['amount'], method: '直接读取，保留同花顺该指数的成交额口径。' },
      { metric: '指数成交量', fields: ['volume'], method: '直接读取，不自行换算来源单位。' },
    ],
    notes: ['前一交易日由 trade_calendar 确定；前收缺失、为零或日历存在未知日期时，不跨缺口计算涨跌幅。', '指数成交额与沪深京个股成交额汇总是两种口径，不能互相替代。'],
  },
  {
    key: 'turnover', label: '市场成交', provider: '同花顺远航版 · 个股历史日线',
    description: '沪深京成交额与 Top 成交额占比，使用同一份已归档个股样本。',
    task: '股票完整历史日K', taskId: 'ths-yuanhang-prices',
    tables: [{ name: 'yuanhang_daily_price', role: '个股日行情事实表' }],
    grain: '一只证券 × 一个交易日', scope: '按 unified_code、trade_date 读取 amount_yuan，金额单位为人民币元。',
    rows: [
      { metric: '沪深京成交额', fields: ['amount_yuan', 'trade_date'], method: '按日期累加已归档沪深京个股的成交额。' },
      { metric: 'Top 成交额占比', fields: ['unified_code', 'trade_date', 'amount_yuan'], method: '按窗口累计成交额排名，取有成交股票前 Top%（数量向上取整）；其累计金额 ÷ 全部样本同期累计金额 × 100%。' },
    ],
    notes: ['这是已归档样本统计，不是官方全市场总额，也不是全市场完整覆盖证明；未归档证券不进入样本。', 'Top 默认 30 个交易日、前 5%，可在已选指标设置中调整；窗口缺整日、金额缺值或分母为零时不计算。沪深京成交额在整日无记录或当日存在金额缺值时不计算。'],
  },
  {
    key: 'margin', label: '融资融券', provider: '同花顺 · 市场融资融券',
    description: '市场级融资与融券数据，区分来源原值、来源合计与系统派生比例。',
    task: '市场融资融券', taskId: 'ths-market-margin',
    tables: [{ name: 'market_margin_daily', role: '市场融资融券日事实表' }],
    grain: '一个市场 × 一个交易日', scope: 'market_code：99 沪深京合计 / 3 沪市 / 2 深市 / 4 京市；按各指标已应用范围读取。',
    rows: [
      { metric: '融资余额', fields: ['financing_balance'], method: '直接读取融资部分余额，单位为元。' },
      { metric: '融券余额', fields: ['lending_balance'], method: '直接读取融券部分余额，单位为元。' },
      { metric: '两融余额', fields: ['source_total', 'financing_balance', 'lending_balance'], method: '优先使用 source_total；缺失时为融资余额 + 融券余额。查询结果名为 total_balance，并非同名存储字段。' },
      { metric: '融资买入额 / 净买入额', fields: ['financing_buy', 'financing_net_buy'], method: '分别直接读取，单位为元。' },
      { metric: '融资买入/偿还比', fields: ['financing_buy', 'financing_net_buy'], method: '偿还额 = 买入额 − 净买入额；比例 = 买入额 ÷ 偿还额 × 100%。偿还额与比例均为系统计算。' },
      { metric: '融券净卖出额', fields: ['lending_net_sell'], method: '直接读取，单位为元。' },
      { metric: '两融余额比例', fields: ['balance_ratio'], method: '来源小数 × 100%，转换为百分数展示。' },
    ],
    notes: ['买入额或净买入额缺失、买入额为负、推导偿还额非正时，不计算买入/偿还比。', '市场两融不代表所选指数的成分股两融；合计与分市场不得相加。融资余额只含融资，两融余额还包含融券。'],
  },
  {
    key: 'fx', label: '汇率行情', provider: '同花顺公开汇率行情 · 日K线与实时报价',
    description: '十二个既有品种的归档收盘与今日 Redis 盘中报价，包含美元指数与伦敦金。',
    task: '汇率历史日线', taskId: 'ths-fx-daily',
    tables: [{ name: 'fx_daily_price', role: '汇率日行情事实表' }],
    snapshot: { task: '汇率实时行情', taskId: 'ths-fx-live', key: '<namespace>:fx:latest' },
    grain: '一个品种 × 一个来源日期', scope: '按 unified_code 及 trade_date 读取，例如 USDCNH.FX；各品种保留自身报价单位。',
    rows: [
      { metric: '各品种收盘', fields: ['close'], method: '读取所选品种的已归档收盘，不使用实时快照补历史。' },
      { metric: '环比变化', fields: ['close', 'trade_date'], method: '（当前收盘 ÷ 前一条已归档日线收盘 − 1）× 100%。' },
      { metric: 'N 期均值', fields: ['close', 'trade_date'], method: '最近 N 条已归档日线收盘的算术均值；异常记录不跳过。' },
      { metric: '价格有效性', fields: ['open', 'high', 'low', 'close'], method: '查询时校验 OHLC 关系；异常值及依赖它的计算显示缺值。' },
    ],
    notes: ['按来源日线日期展示，A股休市仍可有汇率数据；无记录不推断为外汇休市，已归档记录也不证明日期完整。', 'fx_price_year 是年度覆盖校验表，不是收盘事实表，观察页不直接读取。顶部集中标识Redis，默认30秒局部刷新、可调整或关闭；只更新盘中值，归档基准由“刷新数据”更新。Redis只补今天缺少归档记录的品种，不覆盖已有日线或补历史；指数、成交额和两融暂无匹配盘中快照。'],
  },
  {
    key: 'calendar', label: '交易日历', provider: '巨潮资讯 · A股交易日历',
    description: '为月历提供正式交易日与休市日标记，并确定前一交易日及滚动窗口。',
    task: 'A股交易日历', taskId: 'cninfo-calendar',
    tables: [{ name: 'trade_calendar', role: 'A股自然日日历事实表' }],
    grain: '一个自然日', scope: '按 trade_date 读取 is_trade；只描述内地 A 股日历，不替代外汇交易日历。',
    rows: [
      { metric: '日期', fields: ['trade_date'], method: '对应月历自然日。' },
      { metric: '交易 / 休市', fields: ['is_trade'], method: 'true 为正式交易日，false 为来源确认休市日。' },
      { metric: '日历未确认', fields: ['trade_date', 'is_trade'], method: '缺少该日记录时显示未确认，不按周末生成休市标记。' },
    ],
    notes: ['日历辅助读取可能使用已校验缓存，异常时回源 SQL；正式业务表仍为 trade_calendar。', '完整月网格只说明日期展示完整，不代表行情、融资融券或汇率已经采齐；未来日期不展示业务值。'],
  },
];
