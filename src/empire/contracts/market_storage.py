"""Typed market facts: one authoritative field mapping, no raw response persistence."""
import math
from decimal import Decimal, localcontext

SERIES = {
    'trend': ('stock_intraday_trend', ('price', 'average_price', 'source_volume', 'source_flag')),
    'auction': ('stock_opening_auction', ('price', 'source_flag', 'source_volume')),
    'volume': ('stock_minute_volume', ('source_volume', 'source_turnover', 'source_flag')),
    'trades': ('stock_intraday_trade_block', ('price', 'source_flag', 'source_volume',
                                      'source_field_4', 'source_field_5', 'source_field_6', 'source_field_7')),
    'entrust': ('stock_minute_entrust', ('buy_volume', 'sell_volume', 'buy_turnover', 'sell_turnover')),
    'large_order': ('stock_large_order_trend', ('net_amount',)),
}
QUOTE_FIELDS = tuple(('time up_px avg_px low_px down_px high_px last_px open_px pe_rate '
    'jtPeRate TTMPeRate amount_in amplitude px_change vol_ratio amount_out dyn_pb_rate '
    'phcj_volume entrust_rate market_value total_amount total_shares phcj_turnover '
    'px_change_rate total_turnover turnover_ratio circulation_value circulation_amount '
    'actualcirculation_value').split())
EXTRAS = {
    'trend': {'preclose_px'}, 'auction': {'preclose_px'}, 'volume': set(),
    'trades': {'Count', 'total'},
    'entrust': set('maxentrust minentrust maxturnover mineturnover minentrustdiff mineturnoverdiff'.split()),
    'large_order': {'max', 'min'},
    'quote': {'name', 'status', 'sourcetype', 'preclose_px'},
}
BOOK_EXTRAS = {'totalb', 'totals', 'avg_askpx', 'avg_bidpx'}
LAYOUT_VERSION = 2
NUMERIC_SQL = 'DECIMAL(30,12)'
MARKET_TABLES = ('stock_market_day', *(v[0] for v in SERIES.values()),
                 'stock_daily_quote', 'stock_daily_quote_level')


def number(value):
    if type(value) not in (int, float):
        raise ValueError('业务数值必须为来源整数或浮点数')
    if type(value) is int:
        if abs(value) >= 10**18:
            raise ValueError('业务数值超过 DECIMAL(30,12) 无损范围')
        return Decimal(value)
    result = Decimal(str(value))
    exact = result.is_finite() and result.as_tuple().exponent >= -12
    if result.is_finite() and not exact:
        with localcontext() as context:
            context.prec = 40
            exact = result == result.quantize(Decimal('0.000000000001'))
    if (not result.is_finite() or abs(result) >= Decimal('1e18')
            or not exact):
        raise ValueError('业务数值超过 DECIMAL(30,12) 无损范围')
    return result


def numeric_values(values):
    mask = sum(1 << i for i, v in enumerate(values) if type(v) is float)
    mask |= sum(1 << (i+len(values)) for i, v in enumerate(values)
                if type(v) is float and v == 0 and math.copysign(1, v) < 0)
    return [number(v) for v in values], mask


def restore_values(values, mask):
    return [-0.0 if mask & (1 << (i+len(values))) else float(v) if mask & (1 << i) else int(v)
            for i, v in enumerate(values)]


def dataset_tables(kind):
    facts = (SERIES[kind][0],) if kind in SERIES else ('stock_daily_quote', 'stock_daily_quote_level')
    return ('stock_market_day', *facts)
