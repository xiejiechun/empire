"""Web current members: explicit unavailable replaces the current set with empty."""
import re
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.security import index_code, unified_code
from empire.features.yuanhang_indices.contract import MEMBER_DATASET, MEMBER_LIMIT, digest
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {MEMBER_DATASET}
FINGERPRINT_NAMESPACE = 'yuanhang_index_members_v1'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)
TABLES = {'ths_index_member_state': {'index_code', 'available', 'member_count', 'member_hash'},
          'ths_index_member': {'index_code', 'source_code', 'unified_code', 'name'}}
KEYS = {'ths_index_member_state': ['index_code'], 'ths_index_member': ['index_code', 'source_code']}


def member_identity(code):
    if not isinstance(code, str) or not re.fullmatch('[0-9]{5,6}', code):
        raise ValueError('指数成员来源编号无效')
    if len(code) != 6:
        return None
    # Only unambiguous equity prefixes; fund/bond identifiers remain source-only.
    venue = ('SH' if code.startswith(('600', '601', '603', '605', '688', '689', '900')) else
             'SZ' if code.startswith(('000', '001', '002', '003', '200', '300', '301')) else
             'BJ' if code.startswith(('43', '83', '87', '88', '92')) else None)
    return unified_code(venue, code) if venue else None


def normalize(envelope):
    p = envelope.raw_payload
    if set(p) != {'page', 'code', 'available', 'members'} or envelope.business_key != index_code(p['code']):
        raise ValueError('指数成员消息字段无效')
    if type(p['page']) is not int or not 1 <= p['page'] <= 1000:
        raise ValueError('指数成员消息页序无效')
    rows = p['members']
    if type(p['available']) is not bool or not isinstance(rows, list) or len(rows) >= MEMBER_LIMIT or bool(rows) != p['available']:
        raise ValueError('指数成员来源暂无或数量无效')
    previous = ''
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError('指数成员行无效')
        code, name = row
        member_identity(code)
        if code <= previous or not isinstance(name, str) or not name.strip() or len(name) > 100:
            raise ValueError('指数成员重复、乱序或名称无效')
        previous = code
    return {**p, 'identity': p['code'], 'row_count': len(rows)}


def canonical_payload(envelope, data):
    return {k: data[k] for k in ('page', 'code', 'available', 'members')}


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {data['code']: ([data['available'], data['members']],
        [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}


def fingerprint_subset(data, identities):
    return data


def state_unit(data):
    return data['code']


def write(conn, envelope, data):
    require_fixed_source('ths_index_member', envelope.source)
    code = data['code']
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    previous = data['archive_state'].get('units', {}).get(code, {})
    outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
    if observed < previous.get('observed_at', ''):
        return outcome
    head = conn.execute(text('SELECT available,member_count,member_hash FROM ths_index_member_state '
        'WHERE index_code=:code FOR UPDATE'), dict(code=code)).mappings().first()
    old = {r['source_code']: (r['unified_code'], r['name']) for r in conn.execute(text(
        'SELECT source_code,unified_code,name FROM ths_index_member WHERE index_code=:code FOR UPDATE'), dict(code=code)).mappings()}
    new = {r[0]: (member_identity(r[0]), r[1]) for r in data['members']}
    removed = [dict(index=code, code=c) for c in old.keys() - new.keys()]
    if removed:
        conn.execute(text('DELETE FROM ths_index_member WHERE index_code=:index AND source_code=:code'), removed)
    changed = [dict(index=code, code=c, unified=r[0], name=r[1]) for c, r in new.items() if old.get(c) != r]
    if changed:
        conn.execute(text('INSERT INTO ths_index_member(index_code,source_code,unified_code,name) '
            'VALUES(:index,:code,:unified,:name) ON DUPLICATE KEY UPDATE unified_code=VALUES(unified_code),name=VALUES(name)'), changed)
    checksum = digest([data['available'], data['members']])
    count = len(new) if data['available'] else None
    if not head or (bool(head['available']), head['member_count'], head['member_hash']) != (data['available'], count, checksum):
        conn.execute(text('INSERT INTO ths_index_member_state(index_code,available,member_count,member_hash) '
            'VALUES(:code,:available,:count,:hash) ON DUPLICATE KEY UPDATE available=VALUES(available),'
            'member_count=VALUES(member_count),member_hash=VALUES(member_hash)'),
            dict(code=code, available=data['available'], count=count, hash=checksum))
        outcome['written_count'] += 1
    return {**outcome, 'written_count': outcome['written_count'] + len(removed) + len(changed), 'confirmed': [code]}


def archive_state(envelope, data, outcome, previous):
    if not outcome['confirmed']:
        return previous
    unit = dict(hash=digest([data['available'], data['members']]), available=data['available'],
        count=data['row_count'], observed_at=envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds'))
    return dict(contract_version=1, units={**previous.get('units', {}), data['code']: unit},
        progress=confirmed_page(envelope, data, previous))
