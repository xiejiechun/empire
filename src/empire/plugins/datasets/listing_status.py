"""Authoritative bounded month snapshots; typed event facts and one project state."""
from datetime import UTC, date, timedelta

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.listing_status import (
    COLUMNS,
    DATASET,
    FIRST,
    bounds,
    content,
    digest,
    validate_rows,
)
from empire.core.time import CHINA
from empire.plugins.infra.collection_state import confirmed_page

TABLE = 'security_listing_event'
DATASETS = {DATASET}
FINGERPRINT_NAMESPACE = 'tdx_listing_status_v1'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)
TABLES, KEYS = {TABLE: set(COLUMNS)}, {TABLE: list(COLUMNS[:4])}


def read_month(conn, start, end, lock=False):
    records = conn.execute(text(f'SELECT {",".join(COLUMNS)} FROM {TABLE} '
        'WHERE event_date BETWEEN :start AND :end ORDER BY event_date,unified_code,event_type,record_key '
        'LIMIT 5001' + (' FOR UPDATE' if lock else '')), dict(start=start, end=end)).all()
    return [[r[0].isoformat(), *r[1:]] for r in records]


def normalize(envelope):
    p = envelope.raw_payload
    if set(p) != {'page', 'month', 'end', 'rows', 'source_counts'} or type(p['page']) is not int or not 1 <= p['page'] <= 1000:
        raise ValueError('上市状态消息字段或序号无效')
    end = date.fromisoformat(p['end'])
    start, expected_end = bounds(p['month'], end)
    if end != expected_end or p['end'] != end.isoformat() or end > envelope.observed_at.astimezone(CHINA).date():
        raise ValueError('上市状态消息日期上界无效')
    rows = validate_rows(p['rows'], start, end)
    counts = p['source_counts']
    if (not isinstance(counts, list) or len(counts) != (end - start).days + 1
            or any(type(n) is not int or not 0 <= n < 1000 for n in counts)):
        raise ValueError('上市状态核验日期集合缺失或来源总数无效')
    actual = [0] * len(counts)
    for r in rows:
        actual[(date.fromisoformat(r[0]) - start).days] += 1
    if actual != counts:
        raise ValueError('上市状态来源日期集合与规范事件不一致')
    return {**p, 'rows': rows, 'start': start.isoformat(), 'row_count': len(rows)}


def canonical_payload(envelope, data):
    return {k: data[k] for k in ('page', 'month', 'end', 'rows', 'source_counts')}


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {data['month']: (content(data['rows'], data['source_counts']),
        [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}


def fingerprint_subset(data, identities):
    return data


def write(conn, envelope, data):
    require_fixed_source(TABLE, envelope.source)
    proof = data['archive_state'].get('months', {}).get(data['month'], {})
    stamp = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
    if stamp < proof.get('observed_at', ''):
        return outcome
    # A shorter snapshot cannot erase an already confirmed longer month.
    if proof.get('end', data['end']) > data['end']:
        raise ValueError('上市状态月份较新响应范围缩短，须显式核查')
    old = {tuple(r[:4]): r for r in read_month(conn, data['start'], data['end'], lock=True)}
    if len(old) > 5000:
        raise ValueError('上市状态现有月份超限，拒绝不完整替换')
    new = {tuple(r[:4]): r for r in data['rows']}
    removed = old.keys() - new.keys()
    if removed:
        conn.execute(text(f'DELETE FROM {TABLE} WHERE event_date=:event_date AND unified_code=:unified_code '
                          'AND event_type=:event_type AND record_key=:record_key'),
                     [dict(zip(COLUMNS[:4], key, strict=True)) for key in removed])
    changed = [dict(zip(COLUMNS, r, strict=True)) for key, r in new.items() if old.get(key) != r]
    for offset in range(0, len(changed), 500):
        conn.execute(text(f'INSERT INTO {TABLE}({",".join(COLUMNS)}) '
            f'VALUES({",".join(":" + k for k in COLUMNS)}) '
            'ON DUPLICATE KEY UPDATE name=VALUES(name),description=VALUES(description)'), changed[offset:offset + 500])
    outcome.update(written_count=len(removed) + len(changed), confirmed=[data['month']])
    return outcome


def archive_state(envelope, data, outcome, previous):
    if not outcome['confirmed']:
        return previous
    proofs = dict(previous.get('months', {}))
    proofs[data['month']] = dict(start=data['start'], end=data['end'], row_count=len(data['rows']),
        digest=digest(content(data['rows'], data['source_counts'])), source_counts=data['source_counts'],
        observed_at=envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds'), contract=1)
    through = FIRST - timedelta(days=1)
    for month in sorted(proofs):
        p = proofs[month]
        if p.get('contract') != 1 or p.get('start') != (through + timedelta(days=1)).isoformat():
            break
        through = date.fromisoformat(p['end'])
    return dict(months=proofs, coverage_through=through.isoformat() if through >= FIRST else None,
                progress=confirmed_page(envelope, data, previous))
