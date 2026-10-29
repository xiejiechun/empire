"""Date-granular price authority on the existing annual SQL transaction."""
from datetime import UTC, date, timedelta

from empire.core.time import CHINA, mysql_time
from empire.features.yuanhang.repository import _replace, _save_proof, read_rows
from empire.sources.yuanhang_payload import CONTRACT, PRICE_FIELDS, digest
from empire.sources.yuanhang_range_payload import bounds
from empire.sources.yuanhang_ranges import contiguous_through, expand_versions, replace_range


def dates(payload):
    first, last = (date.fromisoformat(v) for v in bounds(payload))
    while first <= last:
        yield first.isoformat()
        first += timedelta(days=1)


def identities(payload):
    rows = {r[0]: r for r in payload['rows']}
    return {payload['code'] + ':' + d: rows.get(d) for d in dates(payload)}


def write_prices(conn, envelope, data, heads):
    h = data['history']
    code, year = h['code'], h['year']
    unit = data['archive_state'].get('units', {}).get(code, {})
    if unit.get('versions') and 'price_ranges' not in unit:
        raise ValueError('远航日线状态需先通过显式维护入口转换为日期覆盖版本')
    old_ranges = unit.get('price_ranges', {})
    segments = old_ranges.get(str(year), [])
    expand_versions(segments, year)
    old = read_rows(conn, code, 'prices', year=year, lock=True)
    if old and not segments:
        raise ValueError('远航日线已有事实缺少日期覆盖版本，请执行维护核查')
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    pending = data.get('pending_days', set(identities(h)))
    incoming = {r[0]: r for r in h['rows']}
    rows, accepted = old, []
    # Group adjacent pending dates to bound merge work after partial cache hits.
    groups = []
    for d in dates(h):
        if code + ':' + d not in pending:
            continue
        if groups and date.fromisoformat(d) == date.fromisoformat(groups[-1][-1]) + timedelta(days=1):
            groups[-1].append(d)
        else:
            groups.append([d])
    for group in groups:
        rows, segments, granted = replace_range(rows, [incoming[d] for d in group if d in incoming],
            year=year, start=group[0], end=group[-1], observed=observed, segments=segments)
        accepted.extend(code + ':' + d for d in granted)
    if not accepted:
        return dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
    count = _replace(conn, 'yuanhang_daily_price', code, rows, old, ('trade_date', *PRICE_FIELDS), 1)
    through = contiguous_through(segments, year)
    if through is None:
        raise ValueError('远航年度缺少年初覆盖；补齐缺口后才能发布年度证明')
    head = heads.get(year)
    proof_observed, native_market = envelope.observed_at, h['native_market']
    if head and head['version_observed_at'] > mysql_time(proof_observed):
        proof_observed = head['version_observed_at'].replace(tzinfo=CHINA)
        native_market = head['native_market']
    proof = dict(quote_year=year, native_market=native_market, source_count=len(rows), row_count=len(rows),
        first_date=rows[0][0] if rows else None, last_date=rows[-1][0] if rows else None,
        key_hash=digest([r[0] for r in rows]), content_hash=digest(rows),
        contract_version=CONTRACT, verified_through=through)
    count += _save_proof(conn, 'yuanhang_price_year', code, proof, head, proof_observed)
    full = dict(unit.get('full_checked', {}))
    if h['contract'] == CONTRACT:
        full[str(year)] = max(full.get(str(year), ''), observed)
    return dict(status='complete', row_count=data['row_count'], written_count=count, confirmed=accepted,
        price_unit=dict(price_ranges={**old_ranges, str(year): segments}, full_checked=full,
                        native_market=native_market))
