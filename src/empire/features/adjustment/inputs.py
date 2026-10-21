"""One read-only SQL snapshot of complete archived inputs, never a second collector."""
from datetime import UTC, date, datetime, timedelta
from itertools import groupby

from sqlalchemy import text

from empire.features.capital_actions.codec import decode
from empire.features.capital_actions.contract import (
    SCHEMA_VERSIONS,
    chain,
    digest,
    ordered,
    unit_key,
    validate_rows,
)
from empire.features.capital_actions.event_rules import ActionError
from empire.features.kaipanla.closing import closing_clock
from empire.features.kaipanla.dates import required_days
from empire.plugins.infra.collection_state import read_state


def proof_time(value):
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp > datetime.now(UTC):
            raise ValueError
        return stamp
    except (TypeError, ValueError):
        raise ActionError('公司行动完整证明的观测版本无效') from None


def capital_rows(conn, table, security=None):
    records = conn.execute(text(f'SELECT *,RIGHT(unified_code,2) AS market,LEFT(unified_code,6) AS code '
        f'FROM {table} ' + ('WHERE unified_code=:security ' if security else '') +
        'ORDER BY unified_code,record_key LIMIT :size'), dict(security=security, size=2001 if security else 10001)).mappings().all()
    if len(records) >= (2001 if security else 10001):
        raise ActionError('公司行动读取超过有界上限')
    result = []
    for stored in records:
        row = decode(stored)
        if digest(row) != stored['content_hash']:
            raise ActionError('公司行动业务内容与存储摘要不匹配', identity=row['record_key'])
        result.append(row)
    return result


def verify_unit(kind, unit, rows, state):
    rows = ordered(rows)
    validate_rows(kind, unit, rows)
    if state.get('contract_version') != SCHEMA_VERSIONS[kind]:
        raise ActionError('公司行动完整证明契约过期，需要补采')
    proof = state.get('units', {}).get(unit, {})
    if proof.get('count') != len(rows) or proof.get('digest') != digest(rows):
        raise ActionError('公司行动尚未采齐或同数异集，完整单元证明不匹配')
    return proof_time(proof.get('observed_at'))


def events(conn, namespace, market, code):
    security, unit = code + '.' + market, market + ':' + code
    div = capital_rows(conn, 'dividend_plan', security)
    div_state = read_state(conn, namespace, 'tdx-dividends', 'tdx')
    observed = [verify_unit('dividends', unit, div, div_state)]
    rights = capital_rows(conn, 'rights_issue')
    state = read_state(conn, namespace, 'tdx-rights-issues', 'tdx')
    if state.get('contract_version') != SCHEMA_VERSIONS['rights_issues']:
        raise ActionError('配股完整来源证明尚未建立')
    keys, rolling = [], digest([])
    for key, group in groupby(sorted(rights, key=unit_key), key=unit_key):
        rows = ordered(list(group))
        verify_unit('rights_issues', key, rows, state)
        keys.append(key)
        rolling = chain(rolling, key, rows)
    actual = dict(units=len(keys), count=len(rights), scope_hash=digest(keys), digest=rolling)
    manifest = state.get('manifest', {})
    if any(manifest.get(k) != v for k, v in actual.items()):
        raise ActionError('配股完整来源集合未匹配，不能把未采集当作没有配股')
    observed.append(proof_time(manifest.get('observed_at')))
    return div, [r for r in rights if unit_key(r) == unit], observed


def suspended(conn, security, lower, upper):
    records = conn.execute(text('SELECT suspended_at,resumed_at FROM suspension_event '
        'WHERE unified_code=:security AND suspension_type=:kind AND suspended_at<:upper '
        'AND resumed_at>:lower ORDER BY suspended_at LIMIT 1001'),
        dict(security=security, kind='full_day', lower=lower, upper=upper + timedelta(days=1))).mappings().all()
    if len(records) > 1000:
        raise ActionError('停牌范围超过有界上限')
    intervals = {}
    for row in records:
        start, end = row['suspended_at'], row['resumed_at']
        if end <= start:
            continue
        first = start.date() + (timedelta(days=1) if start.hour * 60 + start.minute > 570 else timedelta())
        intervals[first] = min(intervals.get(first, end.date()), end.date())
    result = set()
    for first, end in intervals.items():
        day = max(first, lower)
        while day < end and day <= upper:
            result.add(day)
            day += timedelta(days=1)
    return result


def close_prices(conn, query, market, code, lower, upper):
    securities = query.iter_validated_days(conn, market, code, lower, upper)
    result, life = [], None
    for row in securities:
        if life is not None and row['lifecycle'] != life:
            raise ActionError('行情上市生命周期不一致，请补采核实')
        life = row['lifecycle']
        values, day = row['data']['real'], row['trade_date']
        closing_clock(values, day)
        result.append(dict(date=day, **{k: str(values[v]) for k, v in
            (('open', 'open_px'), ('high', 'high_px'), ('low', 'low_px'), ('close', 'last_px'))}))
    if life is None:
        raise ActionError(f'{code}.{market}在{lower}～{upper}没有已归档日行情；'
                              '请在采集管理的“历史盘口与日行情摘要”补齐该证券和日期，再加载K线')
    records = conn.execute(text('SELECT trade_date,is_trade FROM trade_calendar '
        'WHERE trade_date BETWEEN :lower AND :upper ORDER BY trade_date'), dict(lower=lower, upper=upper)).mappings().all()
    if ([r['trade_date'] for r in records] != [lower + timedelta(days=i) for i in range((upper-lower).days+1)]
            or any(r['is_trade'] not in (0, 1) for r in records)):
        raise ActionError('所选范围正式交易日历不完整，不能判断行情缺口')
    trading = [r['trade_date'] for r in records if r['is_trade']]
    expected = set(required_days(dict(listing_date=life['listing_date'], market=market), trading,
                                 suspended(conn, code + '.' + market, lower, upper)))
    actual = {date.fromisoformat(r['date']) for r in result}
    if actual != expected:
        missing = sorted(expected - actual)
        raise ActionError('收盘行情交易日集合不完整或多出非交易日', day=(missing or sorted(actual - expected))[0].isoformat())
    return result
