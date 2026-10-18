"""One incremental typed plan writer; queue ownership belongs to the archiver."""
from datetime import UTC

from sqlalchemy import bindparam, text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.repurchases import (
    COLUMNS,
    DATASET,
    MAX_ROWS,
    PAGE_SIZE,
    digest,
    validate,
)
from empire.core.time import mysql_time
from empire.plugins.infra.collection_state import confirmed_page

TABLE = 'stock_repurchase_plan'
TABLES, KEYS = {TABLE: {*COLUMNS, 'content_hash', 'version_observed_at'}}, {TABLE: ['plan_id']}
DATASETS = {DATASET}
FINGERPRINT_NAMESPACE = 'eastmoney_repurchase_v1'
FINGERPRINT_VERSION = ArchiveVersion(('china', 'utc'), observed_index=1, source_indices=(0,))


def normalize(envelope):
    p = envelope.raw_payload
    if set(p) != {'page', 'rows', 'total', 'collected', 'digest', 'finished'}:
        raise ValueError('回购页消息契约不符')
    if (type(p['page']) is not int or not 1 <= p['page'] <= (MAX_ROWS + 1)
            or type(p['total']) is not int or not 0 <= p['total'] <= MAX_ROWS
            or type(p['collected']) is not int or not 0 <= p['collected'] <= p['total']
            or type(p['finished']) is not bool or p['finished'] != (p['collected'] == p['total'])
            or not isinstance(p['rows'], list) or len(p['rows']) > PAGE_SIZE):
        raise ValueError('回购消息边界无效')
    if not isinstance(p['digest'], str) or len(p['digest']) != 64:
        raise ValueError('回购集合摘要无效')
    bytes.fromhex(p['digest'])
    rows = [validate(r) for r in p['rows']]
    if any(a['plan_id'] >= b['plan_id'] for a, b in zip(rows, rows[1:])):
        raise ValueError('回购消息方案重复或未排序')
    return {**p, 'rows': rows, 'row_count': len(rows)}


def canonical_payload(envelope, data):
    return {k: data[k] for k in ('page', 'rows', 'total', 'collected', 'digest', 'finished')}


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {r['plan_id']: (r, [r['updated_date'] + 'T00:00:00.000000',
        envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')]) for r in data['rows']}


def fingerprint_subset(data, identities):
    rows = [r for r in data['rows'] if r['plan_id'] in identities]
    return {**data, 'rows': rows, 'row_count': len(rows)}


def write(conn, envelope, data):
    require_fixed_source(TABLE, envelope.source)
    observed, confirmed, changed = mysql_time(envelope.observed_at), [], []
    old = {}
    if data['rows']:
        old = {r['plan_id']: dict(r) for r in conn.execute(text(f'SELECT * FROM {TABLE} '
            'WHERE plan_id IN :ids FOR UPDATE').bindparams(bindparam('ids', expanding=True)),
            {'ids': [r['plan_id'] for r in data['rows']]}).mappings()}
    for row in data['rows']:
        previous = old.get(row['plan_id'])
        if previous:
            version = (previous['updated_date'].isoformat(), previous['version_observed_at'])
            if (row['updated_date'], observed) < version:
                continue
            # Compare actual columns so missing historical fields can be repaired.
            content = validate({k: previous[k] for k in COLUMNS})
            if content == row and previous['content_hash'] == digest(row):
                confirmed.append(row['plan_id'])
                continue
        confirmed.append(row['plan_id'])
        changed.append({**row, 'content_hash': digest(row), 'version_observed_at': observed})
    if changed:
        fields = (*COLUMNS, 'content_hash', 'version_observed_at')
        conn.execute(text(f'INSERT INTO {TABLE}({",".join(fields)}) '
            f'VALUES({",".join(":"+k for k in fields)}) ON DUPLICATE KEY UPDATE '
            + ','.join(f'{k}=VALUES({k})' for k in fields if k != 'plan_id')), changed)
    return dict(status='complete', row_count=data['row_count'], written_count=len(changed), confirmed=confirmed)


def archive_state(envelope, data, outcome, previous):
    state = {**previous, 'progress': confirmed_page(envelope, data, previous)}
    if data['finished'] and envelope.observed_at.isoformat() >= previous.get('coverage', {}).get('observed_at', ''):
        state['coverage'] = dict(count=data['total'], digest=data['digest'], contract=1,
                                observed_at=envelope.observed_at.isoformat(timespec='microseconds'))
    return state
