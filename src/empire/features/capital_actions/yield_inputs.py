"""Read existing formal inputs inside the caller's single read-only snapshot."""
from datetime import date, datetime, time, timedelta

from sqlalchemy import text

from empire.core.time import CHINA
from empire.features.calendar.api import read_trade_day_cutoff
from empire.features.calendar.contract import A_SHARE_DAY_END, month_dates
from empire.features.capital_actions.event_rules import ActionError, decimal
from empire.features.kaipanla.closing import closing_clock
from empire.features.suspensions.query import closing_price_evidence
from empire.plugins.infra.collection_state import read_state


def denominator_day(conn, end, now):
    upper = date.fromisoformat(end)
    if upper > now.astimezone(CHINA).date():
        raise ActionError('截止日尚未结束，不使用未来或盘中价格')
    at = min(datetime.combine(upper, time(23, 59, 59), CHINA), now.astimezone(CHINA))
    cutoff, problem = read_trade_day_cutoff(conn, at)
    if cutoff is None:
        raise ActionError(problem)
    if cutoff.date() < upper:
        today = conn.execute(text('SELECT is_trade FROM trade_calendar WHERE trade_date=:day'),
                             dict(day=upper)).scalar_one()
        if today == 1:
            raise ActionError('截止交易日尚未到15:30，不以更早交易日替代')
    return cutoff.date()


def calendar_days(conn, namespace, lower, end, denominator, now):
    # Only the selected range and its boundary month; never a full-history scan.
    first = min(lower, denominator).replace(day=1)
    last = month_dates(end.strftime('%Y-%m'))[-1]
    if (last-first).days > 3660:
        raise ActionError('股息率日期范围最多3660日')
    rows = list(conn.execute(text('SELECT trade_date,is_trade FROM trade_calendar '
        'WHERE trade_date BETWEEN :start AND :end ORDER BY trade_date'), dict(start=first, end=last)).mappings())
    if ([r['trade_date'] for r in rows] != [first+timedelta(days=i) for i in range((last-first).days+1)]
            or any(r['is_trade'] not in (0, 1) for r in rows)):
        raise ActionError('范围内正式交易日历月份不完整，不能推断行情日期')
    state = read_state(conn, namespace, 'cninfo-calendar', 'cninfo')
    stamps = []
    for month in sorted({r['trade_date'].strftime('%Y-%m') for r in rows}):
        try:
            stamp = datetime.fromisoformat(state.get('observed', {}).get(month, ''))
            if stamp.tzinfo is None or stamp > now:
                raise ValueError
        except (ValueError, TypeError):
            raise ActionError('正式日历缺少有效SQL月份确认证据：'+month) from None
        stamps.append(stamp.isoformat())
    return [r['trade_date'] for r in rows if r['is_trade'] and lower <= r['trade_date'] <= denominator], dict(
        source='cninfo', months=sorted({r['trade_date'].strftime('%Y-%m') for r in rows}), observed_at=stamps,
        days=[dict(trade_date=r['trade_date'].isoformat(), is_trade=r['is_trade']) for r in rows])


def price_input(conn, query, security, lower, end, day, expected, now, namespace='empire'):
    if query is None or getattr(query, 'kind', None) != 'quote':
        raise ActionError('历史盘口与日行情摘要正式查询未运行；不能使用其他价格提供者')
    records = list(query.iter_validated_days(conn, security[-2:], security[:6], min(lower, day), day))
    wanted = sorted(set(expected) | {day})
    if [r['trade_date'] for r in records] != [d.isoformat() for d in wanted]:
        raise ActionError('缺少精确分母日价格或区间股数基准日快照；不能改用更早价格')
    heads = list(conn.execute(text('SELECT trade_date,version_observed_at,content_hash FROM stock_market_day '
        "WHERE kind='quote' AND unified_code=:security AND trade_date BETWEEN :start AND :end ORDER BY trade_date"),
        dict(security=security, start=min(lower, day), end=day)).mappings())
    if [h['trade_date'] for h in heads] != wanted:
        raise ActionError('价格证明日期集合不匹配')
    bases, observations, life = set(), [], None
    for row, head in zip(records, heads, strict=True):
        if (row['kind'], row['market'], row['code']) != ('quote', security[-2:], security[:6]):
            raise ActionError('价格类型或证券身份错误；只接受未复权盘口价格')
        if life is not None and life != row['lifecycle']:
            raise ActionError('行情生命周期变化，股数基准不可比')
        life = row['lifecycle']
        real = row['data']['real']
        closing_clock(real, row['trade_date'])
        price = decimal(real.get('last_px'), positive=True)
        low, high = decimal(real.get('low_px'), positive=True), decimal(real.get('high_px'), positive=True)
        if not low <= price <= high:
            raise ActionError('收盘价格不在当日高低价之间')
        if decimal(real.get('total_amount'), positive=True) <= 0:
            raise ActionError('无有效成交，不能把停牌快照当作收盘价')
        bases.add(decimal(real.get('total_shares'), positive=True))
        stamp = head['version_observed_at']
        stamp = stamp.replace(tzinfo=CHINA) if stamp.tzinfo is None else stamp
        closed = datetime.combine(date.fromisoformat(row['trade_date']), A_SHARE_DAY_END, CHINA)
        if not closed <= stamp <= now:
            raise ActionError('行情缺少有效收盘后SQL来源观测证据')
        observations.append(dict(date=row['trade_date'], observed_at=stamp.isoformat(), content_hash=head['content_hash']))
    if len(bases) != 1:
        raise ActionError('区间股数基准变化，简版股息率不可比')
    suspension = closing_price_evidence(conn, namespace, security, day, now)
    last = records[-1]
    return dict(date=day.isoformat(), price=str(last['data']['real']['last_px']), source='kaipanla',
        security=security, adjustment='未复权', source_clock=last['data']['real']['time'],
        observed_at=observations[-1]['observed_at'], basis_shares=str(next(iter(bases))),
        basis_days=len(records), evidence=observations, suspension=suspension)
