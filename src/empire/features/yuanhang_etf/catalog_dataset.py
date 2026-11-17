"""Complete native directory; inactive indices retain their historical identity."""
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.features.yuanhang_etf.contract import CATALOG_DATASET, ETF_LIMIT, digest, identity
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {CATALOG_DATASET}
FINGERPRINT_NAMESPACE = 'yuanhang_etf_catalog_v1'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)
TABLES = {'yuanhang_etf': {'unified_code', 'name', 'native_market', 'active'}}
KEYS = {'yuanhang_etf': ['unified_code']}


def normalize(envelope):
    p = envelope.raw_payload
    if set(p) != {'page', 'catalog'} or p['page'] != 1 or type(p['page']) is not int or envelope.business_key != 'catalog':
        raise ValueError('远航ETF目录消息无效')
    rows = p['catalog']
    if not isinstance(rows, list) or not 1 <= len(rows) <= ETF_LIMIT:
        raise ValueError('远航ETF目录数量无效')
    previous = ''
    for row in rows:
        if not isinstance(row, dict) or set(row) != {'code', 'name', 'native_market'}:
            raise ValueError('远航ETF目录字段无效')
        identity(row['code'], row['native_market'])
        if row['code'] <= previous or not isinstance(row['name'], str) or not row['name'].strip() or row['name'] != row['name'].strip() or len(row['name']) > 100:
            raise ValueError('远航ETF目录重复、乱序或名称无效')
        previous = row['code']
    return {**p, 'identity': 'catalog', 'row_count': len(rows)}


def canonical_payload(envelope, data):
    return {k: data[k] for k in ('page', 'catalog')}


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {'catalog': (data['catalog'], [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}


def fingerprint_subset(data, identities):
    return data


def write(conn, envelope, data):
    require_fixed_source('yuanhang_etf', envelope.source)
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
    if observed < data['archive_state'].get('observed_at', ''):
        return outcome
    old = {r['unified_code']: (r['name'], r['native_market'], bool(r['active'])) for r in conn.execute(
        text('SELECT unified_code,name,native_market,active FROM yuanhang_etf FOR UPDATE')).mappings()}
    new = {r['code']: (r['name'], r['native_market'], True) for r in data['catalog']}
    removed = [dict(code=c) for c, row in old.items() if row[2] and c not in new]
    if removed:
        conn.execute(text('UPDATE yuanhang_etf SET active=FALSE WHERE unified_code=:code'), removed)
    changed = [dict(code=c, name=r[0], market=r[1]) for c, r in new.items() if old.get(c) != r]
    if changed:
        conn.execute(text('INSERT INTO yuanhang_etf(unified_code,name,native_market,active) VALUES(:code,:name,:market,TRUE) '
            'ON DUPLICATE KEY UPDATE name=VALUES(name),native_market=VALUES(native_market),active=TRUE'), changed)
    return {**outcome, 'written_count': len(removed) + len(changed), 'confirmed': ['catalog']}


def archive_state(envelope, data, outcome, previous):
    if not outcome['confirmed']:
        return previous
    return dict(contract_version=1, catalog_hash=digest(data['catalog']), count=data['row_count'],
        observed_at=envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds'),
        progress=confirmed_page(envelope, data, previous))
