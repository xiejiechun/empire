"""One typed authoritative row; source-less revisions use request-start ordering."""
import re
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.listings import (
    COLUMNS,
    CONTRACT,
    DATASET,
    TABLE,
    decode,
    digest,
    validate,
)
from empire.contracts.security import unit_identity
from empire.core.time import CHINA, mysql_time
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {DATASET}
FINGERPRINT_NAMESPACE = 'ths_listings_v2'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)


def normalize(envelope):
    p = envelope.raw_payload
    if (set(p) != {'page', 'unit', 'row', 'manifest'} or type(p['page']) is not int
            or not 1 <= p['page'] <= 15001 or envelope.business_key != p['unit']):
        raise ValueError('上市消息结构或身份无效')
    if p['unit'] == 'manifest':
        m = p['manifest']
        if (p['row'] is not None or not isinstance(m, dict)
                or set(m) != {'scope_hash', 'units', 'refresh_started_at'}
                or type(m['units']) is not int or not 1 <= m['units'] <= 15000
                or not re.fullmatch('[0-9a-f]{64}', str(m['scope_hash']))):
            raise ValueError('上市范围证明无效')
        if m['refresh_started_at'] is not None:
            FINGERPRINT_VERSION.key([m['refresh_started_at']], now=envelope.observed_at)
    else:
        if p['manifest'] is not None:
            raise ValueError('证券消息不能含范围证明')
        row = validate(p['row'], envelope.observed_at.astimezone(CHINA).date().isoformat())
        if row['unified_code'] != unit_identity(p['unit']) or row != p['row']:
            raise ValueError('上市证券身份或数字规范不符')
    return {**p, 'row_count': int(p['row'] is not None)}


def canonical_payload(envelope, data):
    return {k: data[k] for k in ('page', 'unit', 'row', 'manifest')}


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {data['unit']: ({'row': data['row'], 'manifest': data['manifest']},
        [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}


def fingerprint_subset(data, identities):
    return {**data, 'write_unit': data['unit'] in identities}


def state_unit(data):
    return data['unit']


def write(conn, envelope, data):
    require_fixed_source(TABLE, envelope.source)
    unit = data['unit']
    prior = data['archive_state'].get('manifest', {}) if unit == 'manifest' else data['archive_state'].get('units', {}).get(unit, {})
    accepted = data.get('write_unit', True) and envelope.observed_at.isoformat() >= prior.get('observed_at', '')
    outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[unit] if accepted else [])
    if not accepted or unit == 'manifest':
        return outcome
    row = data['row']
    old = conn.execute(text(f'SELECT * FROM {TABLE} WHERE unified_code=:unified_code FOR UPDATE'), row).mappings().first()
    if old and mysql_time(envelope.observed_at) < old['version_observed_at']:
        return {**outcome, 'confirmed': []}
    checksum = digest(row)
    if old and old['contract_version'] == CONTRACT and old['content_hash'] == checksum and decode(old) == row:
        return outcome
    columns = (*COLUMNS, 'content_hash', 'contract_version', 'version_observed_at')
    conn.execute(text(f'INSERT INTO {TABLE} ({",".join(columns)}) VALUES ({",".join(":"+k for k in columns)}) '
        'ON DUPLICATE KEY UPDATE ' + ','.join(f'{k}=VALUES({k})' for k in columns if k != 'unified_code')),
        {**row, 'content_hash': checksum, 'contract_version': CONTRACT, 'version_observed_at': mysql_time(envelope.observed_at)})
    outcome['written_count'] = 1
    return outcome


def archive_state(envelope, data, outcome, previous):
    if data['unit'] not in outcome['confirmed']:
        return previous
    result = {**previous, 'contract_version': CONTRACT, 'progress': confirmed_page(envelope, data, previous)}
    observed = envelope.observed_at.isoformat()
    if data['unit'] == 'manifest':
        result['manifest'] = {**data['manifest'], 'observed_at': observed}
    else:
        result['units'] = {**previous.get('units', {}), data['unit']: {'observed_at': observed,
            'digest': digest(data['row']), 'contract': CONTRACT}}
    return result
