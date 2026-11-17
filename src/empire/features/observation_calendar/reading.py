"""Monthly observation adapter over existing bounded, read-only capabilities."""
import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext

from empire.core.time import CHINA
from empire.features.fx.contract import SYMBOLS

BASE_METRICS = (
    ('close', '指数收盘', '行情', '点', 'index'),
    ('change', '指数涨跌幅', '行情', '%', 'index'),
    ('amount', '指数成交额', '成交', '来源口径', 'index'),
    ('market_amount', '沪深京成交额', '成交', '元', 'equity_market'),
    ('volume', '指数成交量', '成交', '来源口径', 'index'),
    ('financing_balance', '融资余额', '资金', '元', 'market'),
    ('financing_buy', '融资买入额', '资金', '元', 'market'),
    ('financing_repayment_ratio', '融资买入/偿还比', '资金', '%', 'market'),
    ('financing_net_buy', '融资净买入额', '资金', '元', 'market'),
    ('lending_balance', '融券余额', '资金', '元', 'market'),
    ('lending_net_sell', '融券净卖出额', '资金', '元', 'market'),
    ('total_balance', '两融余额', '资金', '元', 'market'),
    ('balance_ratio', '两融余额比例', '资金', '%', 'market'),
    ('top_amount_share', 'Top成交额占比', '成交', '%', 'sample'),
)
FX_METRICS = tuple((f'fx_{code}', f'{name}收盘', '汇率', unit, 'fx')
                   for code, (name, _, unit) in SYMBOLS.items())
METRICS = BASE_METRICS + FX_METRICS
MARKETS = [('99', '沪深京合计'), ('3', '沪市'), ('2', '深市'), ('4', '京市')]


def bounds(month):
    first = date.fromisoformat(month + '-01')
    if not 1991 <= first.year <= 2099:
        raise ValueError('观察月份支持1991～2099年')
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    start = first - timedelta(days=first.weekday())
    end = last + timedelta(days=6-last.weekday())
    previous_month = max(date(1990, 12, 19), (start.replace(day=1) - timedelta(days=1)).replace(day=1))
    return start, end, previous_month


def assemble(month, calendars, prices, margins, today, *, begin_override=None):
    start, end, begin = bounds(month)
    begin = begin_override or begin
    calendar_rows = {r['trade_date']: r['is_trade'] for r in calendars}
    price_rows = {str(r['trade_date']): r for r in prices}
    margin_rows = {str(r['trade_date']): r for r in margins}
    rows, previous = [], None
    current = begin
    while current <= end:
        key = current.isoformat()
        state = calendar_rows.get(key)
        price, margin = price_rows.get(key, {}), margin_rows.get(key, {})
        values = {k: price.get(k) if scope == 'index' else margin.get(k)
                  for k, _, _, _, scope in METRICS}
        values['change'] = None
        with localcontext() as context:
            context.prec = 50
            prior = price_rows.get(previous, {}).get('close')
            close = price.get('close')
            if state is True and prior is not None and Decimal(str(prior)) > 0 and close is not None:
                values['change'] = (Decimal(str(close)) / Decimal(str(prior)) - 1) * 100
            buy, net = margin.get('financing_buy'), margin.get('financing_net_buy')
            values['financing_ratio_buy'] = buy
            values['financing_ratio_repayment'] = None
            values['financing_repayment_ratio'] = None
            if buy is not None and net is not None:
                repayment = Decimal(str(buy)) - Decimal(str(net))
                values['financing_ratio_repayment'] = repayment
                if repayment > 0 and Decimal(str(buy)) >= 0:
                    values['financing_repayment_ratio'] = Decimal(str(buy)) / repayment * 100
            if values['balance_ratio'] is not None:
                values['balance_ratio'] = Decimal(str(values['balance_ratio'])) * 100
        if state is None:
            previous = None  # An unknown calendar day breaks the previous-trading-day proof.
        elif state:
            previous = key
        if current >= (begin if begin_override else start):
            if current > today or state is not True:
                values = {k: None for k in values}
            rows.append(dict(date=key, in_month=key.startswith(month),
                             status='unknown' if state is None else 'trade' if state else 'closed',
                             future=current > today, values=values))
        current += timedelta(days=1)
    return rows


async def catalog(registry):
    indices = await registry.get('index.prices.query').catalog()
    return dict(indices=indices, markets=[dict(code=k, name=v) for k, v in MARKETS],
                metrics=[dict(key=k, name=n, category=c, unit=u, scope=s)
                         for k, n, c, u, s in METRICS])


async def read_base(registry, month, index, market, *, extended=False):
    start, end, begin = bounds(month)
    if extended:
        begin = max(date(1990, 12, 19), start - timedelta(days=366))
    today = datetime.now(CHINA).date()
    calendars = []
    cursor = begin
    while cursor <= end:
        result = await registry.get('calendar.query').month(cursor.strftime('%Y-%m'))
        calendars.extend(result['rows'])
        cursor = (cursor.replace(day=28) + timedelta(days=4)).replace(day=1)
    prices, margins = [], []
    if begin <= today:
        upper = min(end, today).isoformat()
        price_result = await registry.get('index.prices.query').browse(
            code=index, start=begin.isoformat(), end=upper, limit=500 if extended else 200)
        margin_result = await registry.get('market_margin.query').browse(
            search=market, start=begin.isoformat(), end=upper, limit=200)
        if extended and margin_result['next'] is not None:
            second = await registry.get('market_margin.query').browse(
                search=market, start=begin.isoformat(), end=upper, limit=200, after=margin_result['next'])
            margin_result = dict(rows=margin_result['rows'] + second['rows'], next=second['next'])
        if price_result['next'] is not None or margin_result['next'] is not None:
            raise ValueError('观察日历返回超出日期范围，拒绝展示截断结果')
        prices, margins = price_result['rows'], margin_result['rows']
    return dict(month=month, index=index, market=market,
                rows=assemble(month, calendars, prices, margins, today, begin_override=begin if extended else None),
                queried_at=datetime.now(CHINA).isoformat())


