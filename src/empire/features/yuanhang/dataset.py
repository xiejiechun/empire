"""Native price-year and combined financial units on the unified archive path."""
from datetime import UTC

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import mysql_time
from empire.features.yuanhang.contract import FINANCIAL_DATASET, PRICE_DATASET, TABLE_COLUMNS
from empire.features.yuanhang.range_archive import identities, write_prices
from empire.features.yuanhang.repository import read_heads, replace_financial
from empire.plugins.infra.collection_state import confirmed_page
from empire.sources.yuanhang_coverage import financial_proofs
from empire.sources.yuanhang_payload import CONTRACT, validate_financial
from empire.sources.yuanhang_range_payload import validate_price

DATASETS = {PRICE_DATASET, FINANCIAL_DATASET}
FINGERPRINT_NAMESPACE = 'ths_yuanhang_history_v2'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)


def fingerprint_source(envelope):
    # Financial units must not be evicted by the much larger per-day price pool.
    # Keep the existing price bucket; retired financial entries there expire normally.
    return envelope.source + ':financial' if envelope.dataset == FINANCIAL_DATASET else envelope.source


def normalize(envelope):
    p = envelope.raw_payload
    if (set(p) != {'page', 'history'} or type(p['page']) is not int
            or not 1 <= p['page'] <= 2250000):
        raise ValueError('远航版入队结构或页序无效')
    h = (validate_price if envelope.dataset == PRICE_DATASET else validate_financial)(p['history'])
    suffix = str(h['year']) if envelope.dataset == PRICE_DATASET else 'financial'
    identity = h['code'] + ':' + suffix
    if envelope.business_key != identity:
        raise ValueError('远航版消息身份不符')
    count = len(h['rows']) if 'rows' in h else len(h['actions']) + len(h['capital'])
    return dict(page=p['page'], history=h, identity=identity, row_count=count)


def canonical_payload(envelope, data):
    return {k: data[k] for k in ('page', 'history')}


def fingerprint_plan(envelope, data):
    h = data['history']
    if envelope.dataset == PRICE_DATASET:
        version = [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')]
        return FINGERPRINT_NAMESPACE, {key: (dict(row=row, native_market=h['native_market'], contract=6), version)
                                       for key, row in identities(h).items()}
    else:
        content = dict(history=h, proof=financial_proofs(h))
    return FINGERPRINT_NAMESPACE, {data['identity']: (content,
        [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}


def fingerprint_subset(data, identities):
    return {**data, 'write_unit': data['identity'] in identities, 'pending_days': identities}


def state_unit(data):
    return data['history']['code']


def write(conn, envelope, data):
    for table in TABLE_COLUMNS:
        require_fixed_source(table, envelope.source)
    h, ident = data['history'], data['identity']
    code = h['code']
    if 'year' in h:
        return write_prices(conn, envelope, data, read_heads(conn, code, year=h['year'], lock=True))
    token = str(h['year']) if 'year' in h else 'financial'
    previous = data['archive_state'].get('units', {}).get(code, {}).get('versions', {})
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
    if not data.get('write_unit', True) or observed < previous.get(token, ''):
        return outcome
    heads = read_heads(conn, code, year=h.get('year'), lock=True)
    if any(mysql_time(envelope.observed_at) < r['version_observed_at'] for r in heads.values()):
        return outcome
    count = replace_financial(conn, h, envelope.observed_at, heads)
    return {**outcome, 'written_count': count, 'confirmed': [ident]}


def archive_state(envelope, data, outcome, previous):
    if 'year' in data['history']:
        if not outcome['confirmed']:
            return previous
        return dict(contract_version=6, progress=confirmed_page(envelope, data, previous),
                    units={**previous.get('units', {}), data['history']['code']: outcome['price_unit']})
    if data['identity'] not in outcome['confirmed']:
        return previous
    h, code = data['history'], data['history']['code']
    units = dict(previous.get('units', {}))
    old = units.get(code, {})
    token = str(h['year']) if 'year' in h else 'financial'
    versions = {**old.get('versions', {}), token: envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')}
    if len(versions) > 151:
        raise ValueError('远航版单证券版本状态超限')
    units[code] = dict(versions=versions, native_market=h['native_market'],
                        verified_through=h.get('through', old.get('verified_through')))
    return dict(contract_version=CONTRACT, progress=confirmed_page(envelope, data, previous), units=units)
