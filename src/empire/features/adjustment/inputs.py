"""One native-source snapshot; no legacy source or event-plan conversion."""
from datetime import date, timedelta

from sqlalchemy import text

from empire.features.capital_actions.event_rules import ActionError
from empire.features.yuanhang.api import financial_inputs, price_inputs


def close_prices(conn, market, code, lower, upper):
    prices, observed = price_inputs(conn, code + '.' + market, lower, upper)
    # Full native-series proofs establish the sparse trading series. Do not
    # invent suspended-day bars or require every calendar day to have a bar.
    first = max(lower, date.fromisoformat(prices[0]['date']))
    rows = conn.execute(text('SELECT trade_date,is_trade FROM trade_calendar '
        'WHERE trade_date BETWEEN :lower AND :upper ORDER BY trade_date'),
        dict(lower=first, upper=upper)).mappings().all()
    if ([r['trade_date'] for r in rows] != [first + timedelta(days=i) for i in range((upper-first).days+1)]
            or any(r['is_trade'] not in (0, 1) for r in rows)):
        raise ActionError('所选范围正式交易日历不完整')
    trading = {r['trade_date'].isoformat() for r in rows if r['is_trade']}
    if {r['date'] for r in prices} - trading:
        raise ActionError('远航版日线包含正式日历的非交易日期')
    return prices, observed


def events(conn, market, code):
    return financial_inputs(conn, code + '.' + market)