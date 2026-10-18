"""Typed current catalogue and independently atomic index-member sets."""
import hashlib
import json
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.indices import (
    INDEX_LIMIT,
    MEMBER_LIMIT,
    index_code,
    label,
    member_identity,
)
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {'index.catalog', 'index.members'}
CONTRACT_VERSION = 1
FINGERPRINT_NAMESPACE = 'ths_indices_v1'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)
TABLES = {'stock_index': {'index_code', 'name', 'source_group', 'members_available', 'member_count', 'member_hash'},
          'stock_index_member': {'index_code', 'source_code', 'unified_code', 'name'}}
KEYS = {'stock_index': ['index_code'], 'stock_index_member': ['index_code', 'source_code']}


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def validate_catalog(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= INDEX_LIMIT:
        raise ValueError('指数目录范围无效')
    last = ''
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'code', 'name', 'group'}:
            raise ValueError('指数目录字段无效')
        code = index_code(row['code'])
        if code <= last or label(row['name']) != row['name'] or label(row['group'], 40) != row['group']:
            raise ValueError('指数目录重复、乱序或名称未规范化')
        last = code


def normalize(envelope):
    p = envelope.raw_payload
    if type(p.get('page')) is not int or not 1 <= p['page'] <= INDEX_LIMIT + 1:
        raise ValueError('指数消息页序无效')
    if envelope.dataset == 'index.catalog':
        if set(p) != {'page', 'catalog'} or p['page'] != 1 or envelope.business_key != 'catalog':
            raise ValueError('指数目录消息字段无效')
        validate_catalog(p['catalog'])
        return {**p, 'rows': p['catalog'], 'row_count': len(p['catalog']), 'identity': 'catalog'}
    if set(p) != {'page', 'code', 'available', 'members'} or envelope.business_key != index_code(p['code']):
        raise ValueError('指数成员消息字段无效')
    rows = p['members']
    if (type(p['available']) is not bool or not isinstance(rows, list)
            or not 0 <= len(rows) < MEMBER_LIMIT or bool(rows) != p['available']):
        raise ValueError('指数成员可用状态或范围无效')
    last = ''
    for row in rows:
        if not isinstance(row, list) or len(row) != 2:
            raise ValueError('指数成员结构无效')
        code, name = row
        member_identity(code)
        if code <= last or label(name) != name:
            raise ValueError('指数成员重复、乱序或名称无效')
        last = code
    return {**p, 'rows': rows, 'row_count': len(rows), 'identity': p['code']}


def canonical_payload(envelope, data):
    keys = ('page', 'catalog') if envelope.dataset == 'index.catalog' else ('page', 'code', 'available', 'members')
    return {k: data[k] for k in keys}


def content(data):
    return data['catalog'] if data['identity'] == 'catalog' else [data['available'], data['members']]


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {data['identity']: (content(data), [
        envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}


def fingerprint_subset(data, identities):
    return data


def write(conn, envelope, data):
    require_fixed_source('stock_index', envelope.source)
    previous, ident = data['archive_state'], data['identity']
    observed = envelope.observed_at.isoformat(timespec='microseconds')
    proof = previous.get('proofs', {}).get(ident, {})
    outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
    if observed < proof.get('observed_at', ''):
        return outcome
    if ident == 'catalog':
        old = {r['index_code']: (r['name'], r['source_group']) for r in conn.execute(text(
            'SELECT index_code,name,source_group FROM stock_index FOR UPDATE')).mappings()}
        new = {r['code']: (r['name'], r['group']) for r in data['catalog']}
        removed = [{'code': c} for c in old.keys() - new.keys()]
        if removed:
            conn.execute(text('DELETE FROM stock_index_member WHERE index_code=:code'), removed)
            conn.execute(text('DELETE FROM stock_index WHERE index_code=:code'), removed)
        changed = [dict(code=c, name=n[0], category=n[1]) for c, n in new.items() if old.get(c) != n]
        if changed:
            conn.execute(text('INSERT INTO stock_index(index_code,name,source_group) VALUES(:code,:name,:category) '
                'ON DUPLICATE KEY UPDATE name=VALUES(name),source_group=VALUES(source_group)'), changed)
        outcome['written_count'] = len(removed) + len(changed)
    else:
        head = conn.execute(text('SELECT members_available,member_count,member_hash FROM stock_index '
            'WHERE index_code=:code FOR UPDATE'), {'code': ident}).mappings().first()
        if head is None:
            if observed <= previous.get('proofs', {}).get('catalog', {}).get('observed_at', ''):
                return outcome
            raise ValueError('指数成员缺少已归档目录关联')
        old = {r['source_code']: (r['unified_code'], r['name']) for r in conn.execute(text(
            'SELECT source_code,unified_code,name FROM stock_index_member WHERE index_code=:code FOR UPDATE'),
            {'code': ident}).mappings()}
        new = {r[0]: (member_identity(r[0]), r[1]) for r in data['members']} if data['available'] else old
        removed = [dict(index=ident, code=c) for c in old.keys() - new.keys()]
        if removed:
            conn.execute(text('DELETE FROM stock_index_member WHERE index_code=:index AND source_code=:code'), removed)
        changed = [dict(index=ident, code=c, unified=n[0], name=n[1]) for c, n in new.items() if old.get(c) != n]
        if changed:
            conn.execute(text('INSERT INTO stock_index_member(index_code,source_code,unified_code,name) '
                'VALUES(:index,:code,:unified,:name) ON DUPLICATE KEY UPDATE unified_code=VALUES(unified_code),name=VALUES(name)'), changed)
        checksum = digest(content(data))
        if (head['members_available'], head['member_count'], head['member_hash']) != (data['available'], len(new), checksum):
            conn.execute(text('UPDATE stock_index SET members_available=:available,member_count=:count,member_hash=:hash '
                'WHERE index_code=:code'), dict(available=data['available'], count=len(new), hash=checksum, code=ident))
            outcome['written_count'] += 1
        outcome['written_count'] += len(removed) + len(changed)
    outcome['confirmed'] = [ident]
    # Catalogue deletions invalidate member proofs too. The archive owner resets
    # this source scope after commit, including equality on commit/Redis replay.
    outcome['reset_fingerprints'] = ident == 'catalog'
    return outcome


def archive_state(envelope, data, outcome, previous):
    if not outcome['confirmed']:
        return previous
    proofs = dict(previous.get('proofs', {}))
    if data['identity'] == 'catalog':
        current = {r['code'] for r in data['catalog']} | {'catalog'}
        proofs = {k: v for k, v in proofs.items() if k in current}
    proofs[data['identity']] = dict(hash=digest(content(data)),
        observed_at=envelope.observed_at.isoformat(timespec='microseconds'), count=data['row_count'])
    return dict(contract_version=CONTRACT_VERSION, proofs=proofs,
                progress=confirmed_page(envelope, data, previous))
