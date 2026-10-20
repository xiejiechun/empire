"""Persistent BSE identities through the shared archive and fingerprint owner."""
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import mysql_time
from empire.features.security_aliases.contract import URL, validate
from empire.plugins.infra.collection_state import confirmed_page
from empire.plugins.pipeline.fingerprints import digest

JOB, PROJECT = 'bse-code-mapping-v1', 'bse-code-mapping'
DATASETS = {'bse.code_mapping.complete'}
FINGERPRINT_NAMESPACE = 'bse_code_mapping_v1'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)
TABLES = {'security_code_alias': {'legacy_code', 'unified_code', 'name', 'listing_date', 'version_observed_at'}}
KEYS = {'security_code_alias': ['legacy_code']}


def normalize(envelope):
    p = envelope.raw_payload
    if (set(p) != {'page', 'rows', 'source_count', 'source_url'} or p['page'] != 1
            or type(p['page']) is not int or envelope.business_key != 'official-table'
            or p['source_url'] != URL or type(p['source_count']) is not int
            or p['source_count'] != len(p['rows'])):
        raise ValueError('北交所映射完整表证明无效')
    validate(p['rows'])
    if p['rows'] != sorted(p['rows'], key=lambda row: row['legacy_code']):
        raise ValueError('北交所映射规范顺序错误')
    return {**p, 'row_count': len(p['rows'])}


def canonical_payload(envelope, data):
    return {key: data[key] for key in ('page', 'rows', 'source_count', 'source_url')}


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {'official-table': (data['rows'], [
        envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}


def fingerprint_subset(data, identities):
    return data


def write(conn, envelope, data):
    require_fixed_source('security_code_alias', envelope.source)
    result = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
    previous = data['archive_state']
    version = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    if version < previous.get('observed_at', ''):
        return result
    old = {row['legacy_code']: row for row in conn.execute(text(
        'SELECT legacy_code,unified_code,name,listing_date,version_observed_at FROM security_code_alias FOR UPDATE')).mappings()}
    reverse = {row['unified_code']: key for key, row in old.items()}
    changed = []
    # DATETIME has second precision. Truncate before binding so MySQL cannot
    # round a response into the future; archive_state retains exact ordering.
    stamp = mysql_time(envelope.observed_at).replace(microsecond=0)
    for row in data['rows']:
        stored = old.get(row['legacy_code'])
        if (stored and stored['unified_code'] != row['unified_code']) or reverse.get(row['unified_code'], row['legacy_code']) != row['legacy_code']:
            raise ValueError('北交所证券身份映射冲突，须核实来源后显式维护')
        if stored:
            if stamp < stored['version_observed_at']:
                return result
            if (stored['name'], stored['listing_date'].isoformat()) == (row['name'], row['listing_date']):
                continue
        changed.append({**row, 'observed': stamp})
    if changed:
        conn.execute(text('INSERT INTO security_code_alias(legacy_code,unified_code,name,listing_date,version_observed_at) '
            'VALUES(:legacy_code,:unified_code,:name,:listing_date,:observed) ON DUPLICATE KEY UPDATE '
            'name=VALUES(name),listing_date=VALUES(listing_date),version_observed_at=VALUES(version_observed_at)'), changed)
    result.update(written_count=len(changed), confirmed=['official-table'])
    return result


def archive_state(envelope, data, outcome, previous):
    if not outcome['confirmed']:
        return previous
    return dict(contract_version=1, observed_at=envelope.observed_at.isoformat(timespec='microseconds'),
        count=data['row_count'], hash=digest(data['rows']), source_url=URL,
        progress=confirmed_page(envelope, data, previous))
