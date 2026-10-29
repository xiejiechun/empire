"""Explicit range messages; complete-year messages retain their existing contract."""
from datetime import date

from empire.sources.yuanhang_history import DailyBar
from empire.sources.yuanhang_payload import (
    PRICE_FIELDS,
    _identity,
    _rows,
    day,
    digest,
    number,
    validate_year,
)


def bounds(payload):
    if payload['contract'] == 6:
        return payload['start'], payload['through']
    return f"{payload['year']}-01-01", min(payload['through'], f"{payload['year']}-12-31")


def validate_price(payload):
    if type(payload) is not dict or type(payload.get('contract')) is not int:
        raise ValueError('远航日线消息契约类型无效')
    if payload.get('contract') != 6:
        return validate_year(payload)
    if set(payload) != {'contract', 'code', 'native_market', 'year', 'start', 'through',
                        'rows', 'source_count', 'key_hash'}:
        raise ValueError('远航区间消息契约无效')
    _identity(payload['code'], payload['native_market'])
    first, last = day(payload['start']), day(payload['through'])
    if (type(payload['year']) is not int or first.year != payload['year']
            or last.year != payload['year'] or first > last):
        raise ValueError('远航区间消息年度或边界无效')
    _rows(payload['rows'], PRICE_FIELDS, kind='daily')
    if (type(payload['source_count']) is not int or payload['source_count'] != len(payload['rows'])
            or payload['key_hash'] != digest([r[0] for r in payload['rows']])
            or any(not first <= day(r[0]) <= last for r in payload['rows'])):
        raise ValueError('远航区间集合、数量或日期不符')
    return payload


def daily_ranges(snapshot, *, code, start, through):
    _identity(code, snapshot.native_market)
    if not isinstance(snapshot.data, tuple) or not 1 <= len(snapshot.data) <= 150 * 366:
        raise ValueError('远航区间须来自非空且完整的身份响应')
    if not date(1900, 1, 1) <= start <= through <= date(2100, 12, 31):
        raise ValueError('远航区间日期无效')
    grouped, previous = {}, None
    for bar in snapshot.data:
        if (not isinstance(bar, DailyBar) or bar.unified_code != code
                or not start <= bar.trade_date <= through
                or previous is not None and bar.trade_date <= previous):
            raise ValueError('远航区间来源身份、排序或日期无效')
        previous = bar.trade_date
        grouped.setdefault(bar.trade_date.year, []).append([bar.trade_date.isoformat()] + [
            number(getattr(bar, k), nullable=k in ('volume_shares', 'amount_yuan')) for k in PRICE_FIELDS])
    result = []
    for year in range(start.year, through.year + 1):
        rows = grouped.get(year, [])
        result.append(validate_price(dict(contract=6, code=code, native_market=snapshot.native_market,
            year=year, start=max(start, date(year, 1, 1)).isoformat(),
            through=min(through, date(year, 12, 31)).isoformat(), rows=rows,
            source_count=len(rows), key_hash=digest([r[0] for r in rows]))))
    return result
