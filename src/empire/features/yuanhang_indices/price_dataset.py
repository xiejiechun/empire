"""Native index ranges with shared per-date version merge and typed facts."""
from datetime import UTC, date, timedelta

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import mysql_time
from empire.features.yuanhang_indices.contract import (
    FIELDS,
    PRICE_DATASET,
    day,
    digest,
    identity,
    number,
    validate_rows,
)
from empire.plugins.infra.collection_state import confirmed_page
from empire.sources.yuanhang_ranges import contiguous_through, replace_range, versions_on

DATASETS = {PRICE_DATASET}
FINGERPRINT_NAMESPACE = 'yuanhang_index_prices_v1'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)
TABLES = {'yuanhang_index_daily_price': {'index_code', 'trade_date', *FIELDS},
          'yuanhang_index_price_year': {'index_code', 'quote_year', 'native_market', 'row_count',
            'first_date', 'last_date', 'key_hash', 'content_hash', 'verified_through', 'contract_version', 'version_observed_at'}}
KEYS = {'yuanhang_index_daily_price': ['index_code', 'trade_date'], 'yuanhang_index_price_year': ['index_code', 'quote_year']}


def normalize(envelope):
    p = envelope.raw_payload
    if set(p) != {'page', 'code', 'native_market', 'start', 'through', 'rows', 'full', 'history_start'}:
        raise ValueError('远航指数日K消息契约无效')
    identity(p['code'], p['native_market'])
    validate_rows(p['rows'], p['start'], p['through'])
    if p['full']:
        if day(p['history_start']) > p['through']:
            raise ValueError('指数完整历史起点无效')
    elif p['history_start'] is not None:
        raise ValueError('指数区间不能声明完整历史起点')
    year = int(p['start'][:4])
    ident = p['code'] + ':' + str(year)
    if envelope.business_key != ident or type(p['page']) is not int or not 1 <= p['page'] <= 150000 or type(p['full']) is not bool:
        raise ValueError('远航指数日K消息身份、页号或初始化标记无效')
    return {**p, 'year': year, 'identity': ident, 'row_count': len(p['rows'])}


def canonical_payload(envelope, data):
    return {k: data[k] for k in ('page', 'code', 'native_market', 'start', 'through', 'rows', 'full', 'history_start')}


def date_keys(data):
    first, last = date.fromisoformat(data['start']), date.fromisoformat(data['through'])
    rows = {r[0]: r for r in data['rows']}
    result = {}
    while first <= last:
        stamp = first.isoformat()
        result[data['code'] + ':' + stamp] = rows.get(stamp)
        first += timedelta(days=1)
    return result


def fingerprint_plan(envelope, data):
    version = [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')]
    return FINGERPRINT_NAMESPACE, {key: (dict(row=row, native_market=data['native_market'], full=data['full'], history_start=data['history_start']), version)
                                   for key, row in date_keys(data).items()}


def fingerprint_subset(data, identities):
    return {**data, 'pending_days': identities}


def state_unit(data):
    return data['code']


def sql_rows(conn, code, year, lock=False):
    rows = conn.execute(text('SELECT trade_date,open,high,low,close,volume,amount FROM yuanhang_index_daily_price '
        'WHERE index_code=:code AND trade_date BETWEEN :first AND :last ORDER BY trade_date LIMIT 367'
        + (' FOR UPDATE' if lock else '')), dict(code=code, first=f'{year}-01-01', last=f'{year}-12-31')).all()
    if len(rows) > 366:
        raise ValueError('指数年度事实超过366天')
    return [[r[0].isoformat()] + [number(v) for v in r[1:]] for r in rows]


def write(conn, envelope, data):
    require_fixed_source('yuanhang_index_daily_price', envelope.source)
    code, year = data['code'], data['year']
    unit = data['archive_state'].get('units', {}).get(code, {})
    if unit.get('native_market', data['native_market']) != data['native_market']:
        raise ValueError('指数原生市场变更须显式核查，不能混合两个市场的行情')
    ranges = unit.get('price_ranges', {})
    segments = ranges.get(str(year), [])
    old = sql_rows(conn, code, year, True)
    if old and not segments:
        raise ValueError('指数旧事实缺少可信区间，须显式核查')
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    pending = data.get('pending_days', set(date_keys(data)))
    incoming = {r[0]: r for r in data['rows']}
    rows, accepted, groups = old, [], []
    for key in date_keys(data):
        if key not in pending:
            continue
        stamp = key[-10:]
        if groups and date.fromisoformat(stamp) == date.fromisoformat(groups[-1][-1]) + timedelta(days=1):
            groups[-1].append(stamp)
        else:
            groups.append([stamp])
    for group in groups:
        rows, segments, granted = replace_range(rows, [incoming[d] for d in group if d in incoming],
            year=year, start=group[0], end=group[-1], observed=observed, segments=segments)
        accepted.extend(code + ':' + d for d in granted)
    outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=accepted)
    if not accepted:
        return outcome
    old_map, new_map = {r[0]: r for r in old}, {r[0]: r for r in rows}
    removed = [dict(code=code, day=d) for d in old_map.keys() - new_map.keys()]
    if removed:
        conn.execute(text('DELETE FROM yuanhang_index_daily_price WHERE index_code=:code AND trade_date=:day'), removed)
    changed = [dict(code=code, day=d, **dict(zip(FIELDS, r[1:], strict=True))) for d, r in new_map.items() if old_map.get(d) != r]
    if changed:
        conn.execute(text('INSERT INTO yuanhang_index_daily_price(index_code,trade_date,open,high,low,close,volume,amount) '
            'VALUES(:code,:day,:open,:high,:low,:close,:volume,:amount) ON DUPLICATE KEY UPDATE '
            + ','.join(f'{f}=VALUES({f})' for f in FIELDS)), changed)
    through = contiguous_through(segments, year)
    head = conn.execute(text('SELECT * FROM yuanhang_index_price_year WHERE index_code=:code AND quote_year=:year FOR UPDATE'),
        dict(code=code, year=year)).mappings().first()
    proof = dict(native_market=data['native_market'], row_count=len(rows), first_date=rows[0][0] if rows else None,
        last_date=rows[-1][0] if rows else None, key_hash=digest([r[0] for r in rows]), content_hash=digest(rows),
        verified_through=through, contract_version=1)
    same = head and all((v.isoformat() if isinstance(v := head[k], date) else v) == expected for k, expected in proof.items())
    if not same:
        fields = ('index_code', 'quote_year', *proof, 'version_observed_at')
        conn.execute(text('INSERT INTO yuanhang_index_price_year (' + ','.join(fields) + ') VALUES ('
            + ','.join(':' + k for k in fields) + ') ON DUPLICATE KEY UPDATE '
            + ','.join(f'{k}=VALUES({k})' for k in fields[2:])),
            dict(index_code=code, quote_year=year, **proof,
                 version_observed_at=max(head['version_observed_at'], mysql_time(envelope.observed_at))
                 if head else mysql_time(envelope.observed_at)))
    full_years = dict(unit.get('full_years', {}))
    covered = versions_on(segments, year, [key[-10:] for key in date_keys(data)])
    if data['full'] and len(covered) == len(date_keys(data)):
        full_years[str(year)] = max(full_years.get(str(year), observed), observed)
    starts = [v for v in (data['history_start'], unit.get('history_start')) if v]
    return {**outcome, 'written_count': len(removed) + len(changed) + int(not same),
        'price_unit': dict(native_market=data['native_market'], price_ranges={**ranges, str(year): segments},
                           full_years=full_years, history_start=min(starts) if starts else None)}


def archive_state(envelope, data, outcome, previous):
    if not outcome['confirmed']:
        return previous
    return dict(contract_version=1, units={**previous.get('units', {}), data['code']: outcome['price_unit']},
        progress=confirmed_page(envelope, data, previous))
