"""Bounded native-history business payloads, before any publication or SQL write.

The native decoder proves response completeness. This boundary retains that
proof while splitting daily history; it never infers a successful empty reply.
"""
import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from empire.sources.yuanhang_history import (
    CorporateAction,
    DailyBar,
    FinancialHistory,
    security_identity,
)

CONTRACT = 5
FIRST = date(1900, 1, 1)
FINANCIAL_END = date(2100, 12, 31)
PRICE_FIELDS = ('open', 'high', 'low', 'close', 'volume_shares', 'amount_yuan')
ACTION_FIELDS = ('bonus_ratio', 'transfer_ratio', 'rights_ratio', 'rights_price', 'cash_per_share')
CAPITAL_KINDS = ('circulating', 'free_float', 'total')


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def action_key(row):
    """Stable event identity; date is separately part of the business key."""
    return digest(row[1:])


def number(value, *, nullable=False, signed=False):
    if value is None and nullable:
        return None
    if type(value) not in (str, Decimal, int):
        raise ValueError('远航版业务数值类型无效')
    try:
        n = Decimal(value)
        if (not n.is_finite() or (n <= -1 if signed else n < 0) or n >= Decimal(10) ** 18
                or n != n.quantize(Decimal('0.0000000001'))):
            raise ValueError('远航版业务数值越界或精度超限')
    except InvalidOperation as exc:
        raise ValueError('远航版业务数值无效') from exc
    return '0' if n == 0 else format(n.normalize(), 'f')


def day(value):
    if type(value) is not str:
        raise ValueError('远航版业务日期必须为ISO日期')
    result = date.fromisoformat(value)
    if result.isoformat() != value or not FIRST <= result <= FINANCIAL_END:
        raise ValueError('远航版业务日期超出支持范围')
    return result


def _rows(rows, fields, *, kind):
    limit = 366 if kind == 'daily' else 2000
    if type(rows) is not list or len(rows) > limit:
        raise ValueError('远航版完整单元点数超限')
    last = ('', '')
    for row in rows:
        if type(row) is not list or len(row) != len(fields) + 1:
            raise ValueError('远航版业务行结构无效')
        day(row[0])
        key = (row[0], action_key(row) if kind == 'actions' else '')
        if key <= last:
            raise ValueError('远航版业务日期重复或乱序')
        last = key
        for key, value in zip(fields, row[1:], strict=True):
            if number(value, nullable=key in ('volume_shares', 'amount_yuan'), signed=key == 'bonus_ratio') != value:
                raise ValueError('远航版业务数字未规范化')
        values = dict(zip(fields, row[1:], strict=True))
        if kind == 'daily':
            op, high, low, close = (Decimal(values[k]) for k in PRICE_FIELDS[:4])
            if min(op, high, low, close) <= 0:
                raise ValueError('远航版业务价格必须为正数')
        else:
            if Decimal(values['bonus_ratio']) < 0 and any(Decimal(values[k]) != 0 for k in fields if k != 'bonus_ratio'):
                raise ValueError('远航版负送缩股比例只接受纯缩股事件')
            if Decimal(values['rights_ratio']) > 0 and Decimal(values['rights_price']) <= 0:
                raise ValueError('远航版配股缺少有效认购价格')


def _identity(code, market):
    if market is None:
        raise ValueError('远航版消息必须保留实际原生市场')
    security_identity(code, market)


def daily_years(snapshot, *, code, through):
    """Validate the entire nonempty full response before returning annual units."""
    _identity(code, snapshot.native_market)
    end = day(through.isoformat())
    bars = snapshot.data
    if not isinstance(bars, tuple) or not 1 <= len(bars) <= 150 * 366:
        raise ValueError('远航版完整日线响应为空或超限')
    grouped = {}
    last = FIRST
    for bar in bars:
        if not isinstance(bar, DailyBar) or bar.unified_code != code:
            raise ValueError('远航版日线响应混入其他证券')
        if not FIRST <= bar.trade_date <= end or (grouped and bar.trade_date <= last):
            raise ValueError('远航版日线日期重复、乱序或越界')
        last = bar.trade_date
        grouped.setdefault(last.year, []).append([last.isoformat()] + [
            number(getattr(bar, k), nullable=k in ('volume_shares', 'amount_yuan')) for k in PRICE_FIELDS])
    first = bars[0].trade_date
    if not 1 <= end.year - first.year + 1 <= 150:
        raise ValueError('远航版日线年度跨度超限')
    result = []
    for year in range(first.year, end.year + 1):
        rows = grouped.get(year, [])
        payload = dict(contract=CONTRACT, code=code, native_market=snapshot.native_market,
                       year=year, through=through.isoformat(), history_first=first.isoformat(),
                       history_last=last.isoformat(), history_count=len(bars), rows=rows,
                       source_count=len(rows), key_hash=digest([r[0] for r in rows]))
        validate_year(payload)
        result.append(payload)
    return result


def validate_year(p):
    if type(p) is not dict or set(p) != {
        'contract', 'code', 'native_market', 'year', 'through', 'history_first',
        'history_last', 'history_count', 'rows', 'source_count', 'key_hash',
    } or type(p['contract']) is not int or p['contract'] != CONTRACT:
        raise ValueError('远航版年度消息契约无效')
    _identity(p['code'], p['native_market'])
    first, last, end = (day(p[k]) for k in ('history_first', 'history_last', 'through'))
    year = p['year']
    if (type(year) is not int or not first <= last <= end
            or not first.year <= year <= end.year or end.year - first.year >= 150
            or type(p['history_count']) is not int or not 1 <= p['history_count'] <= 150 * 366):
        raise ValueError('远航版年度来源边界无效')
    rows = p['rows']
    _rows(rows, PRICE_FIELDS, kind='daily')
    if (type(p['source_count']) is not int or p['source_count'] != len(rows)
            or p['source_count'] > p['history_count']
            or p['key_hash'] != digest([r[0] for r in rows])
            or any(not first <= day(r[0]) <= last or day(r[0]).year != year for r in rows)):
        raise ValueError('远航版年度集合、数量或范围不符')
    if ((year == first.year and (not rows or rows[0][0] != first.isoformat()))
            or (year == last.year and (not rows or rows[-1][0] != last.isoformat()))):
        raise ValueError('远航版年度遗漏源首尾记录')
    return p


def financial_payload(snapshot, *, code):
    _identity(code, snapshot.native_market)
    history = snapshot.data
    if not isinstance(history, FinancialHistory):
        raise ValueError('远航版必须使用已校验联合金融响应')
    if any(not isinstance(a, CorporateAction) or a.unified_code != code for a in history.actions):
        raise ValueError('远航版权息响应证券不符')
    if any(c.unified_code != code for c in history.capital):
        raise ValueError('远航版股本响应证券不符')
    payload = dict(contract=CONTRACT, code=code, native_market=snapshot.native_market,
                   actions=[[a.ex_date.isoformat()] + [number(getattr(a, k), signed=k == 'bonus_ratio') for k in ACTION_FIELDS]
                            for a in history.actions],
                   capital=[[c.kind, c.effective_date.isoformat(), number(c.shares, nullable=c.kind == 'circulating')]
                            for c in history.capital])
    payload['actions'].sort(key=lambda row: (row[0], action_key(row)))
    return validate_financial(payload)


def validate_financial(p):
    if (type(p) is not dict or set(p) != {'contract', 'code', 'native_market', 'actions', 'capital'}
            or type(p['contract']) is not int or p['contract'] != CONTRACT):
        raise ValueError('远航版金融消息契约无效')
    _identity(p['code'], p['native_market'])
    _rows(p['actions'], ACTION_FIELDS, kind='actions')
    capital = p['capital']
    if type(capital) is not list or not 3 <= len(capital) <= 30000:
        raise ValueError('远航版股本序列点数无效')
    previous, kinds = ('', ''), set()
    for row in capital:
        if type(row) is not list or len(row) != 3 or row[0] not in CAPITAL_KINDS:
            raise ValueError('远航版股本行结构无效')
        day(row[1])
        key = tuple(row[:2])
        if (key <= previous or number(row[2], nullable=row[0] == 'circulating') != row[2]
                or row[2] is not None and Decimal(row[2]) <= 0):
            raise ValueError('远航版股本重复、乱序或数值无效')
        previous = key
        kinds.add(row[0])
    if kinds != set(CAPITAL_KINDS):
        raise ValueError('远航版联合响应缺少必要股本口径')
    return p
