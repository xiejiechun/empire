"""Research templates refer to the one data catalogue; they never register collectors."""
from empire.contracts.preparation_scope import FOCUSES, STUDIES
from empire.features.preparation.catalog import BY_ID

RESEARCH_VERSION = 1
SIGNALS = {
    'price': ('historical_quote', 'adjusted_prices'),
    'valuation': ('pe', 'pb', 'ps', 'market_value', 'dividend_yield'),
    'quality': ('income', 'balance', 'cashflow', 'financial_reconciliation'),
    'holders': ('top_holders', 'float_holders', 'holder_count', 'shareholder_changes'),
    'flows': ('large_order_trend', 'minute_entrust'),
}
VALUE = {
    'operating': ('income', 'balance', 'cashflow'),
    'valuation': ('pe', 'pb', 'ps', 'dividend_yield'),
    'returns': ('dividends', 'repurchases', 'rights_issues', 'additional_issues'),
    'risk': ('top_holders', 'pledge', 'freeze', 'related_transactions',
             'capital_projects', 'capital_acquisitions'),
}
EXECUTION = ('suspensions', 'st_implementation', 'st_removal', 'limit_rules',
             'settlement_rules', 'lot_rules', 'tick_rules', 'sessions', 'stamp_duty',
             'transfer_fee', 'dividends', 'rights_issues', 'index_prices')


def required_ids(scope):
    if not scope.study:
        return set(BY_ID)
    selected = {'universe', 'calendar'}
    selected.update(VALUE[scope.focus] if scope.study == 'value' else SIGNALS[scope.focus])
    if scope.study != 'value':
        selected.update(('listings', 'delistings', 'historical_quote'))
    if scope.study == 'backtest':
        selected.update(EXECUTION)
    def expand(ident):
        for dependency in BY_ID[ident].dependencies:
            if dependency not in selected:
                selected.add(dependency)
                expand(dependency)
    for ident in tuple(selected):
        expand(ident)
    return selected


def research_guards(scope):
    """Missing research products remain explicit, even when all raw checks pass."""
    if not scope.study:
        return []
    guards = []
    def add(title, state, detail):
        guards.append(dict(title=title, state=state, detail=detail))
    if scope.study != 'value':
        add('研究日期', '通过' if scope.start and scope.end else '阻断',
            '历史研究须明确起止日期；回看期和收益标签成熟期仍须在研究计算中单独校验。')
        add('历史股票池', '有限制' if scope.codes else '阻断',
            '指定证券仅代表固定样本，存在选择偏差；当前股票名单不能还原历史全市场和退市样本。'
            if scope.codes else '尚无完整历史股票池证明；当前池不能作为无幸存者偏差的历史全市场。')
        add('因子矩阵与收益标签', '待建设',
            '本页验收原料及已有计算输入；因子矩阵、回看窗口、标签和IC/分组效果尚未登记正式产物。')
        add('信号与交易时间', '有限制',
            '收盘数据最早用于下一可交易日；财务/股东信号必须有实际公布或可用日期，入库时间不能替代。')
    if scope.study == 'backtest':
        add('成交与成本模型', '待建设',
            '尚无正式回测引擎；佣金、最低佣金、滑点、容量和涨跌停成交假设须由策略明确。日线不能证明排队成交。')
        add('基准收益口径', '有限制' if scope.index_codes else '阻断',
            '须指定同花顺基准指数；当前指数行情为价格口径，不代表全收益指数。')
    if scope.study == 'value':
        add('当前版本研究', '有限制',
            '用于现在研究历史经营趋势；报表可能经过后续修订，缺公告日期不能据此回放过去财务选股。')
        add('观察年限与行业口径', '有限制',
            '建议检查5～10年；上市/来源不足须按实际范围解释。银行、保险、券商不可套一般企业指标。'
            'TTM、自由现金流、ROIC及DCF情景尚未登记正式计算产物。')
    return guards


def research_summary(rows, scope):
    required = required_ids(scope)
    selected = [row for row in rows if row['id'] in required]
    counts = dict(ready=0, limited=0, blocked=0, unknown=0, planned=0)
    for row in selected:
        assessment = row['assessment']
        state = ('planned' if not row['registered'] else
                 'limited' if assessment['usable'] and assessment['use_state'] != '可用' else
                 'ready' if assessment['usable'] else
                 'blocked' if assessment['use_state'] in ('不可用', '依赖未满足') else 'unknown')
        counts[state] += 1
    guards = research_guards(scope)
    return dict(title=STUDIES.get(scope.study, '全部数据'),
                focus=FOCUSES.get(scope.study, {}).get(scope.focus, '来源声明范围'),
                required=len(selected), counts=counts, guards=guards,
                ready=not any(counts[k] for k in ('blocked', 'unknown', 'planned'))
                and not any(g['state'] in ('阻断', '待建设') for g in guards))
