"""Statement mappings; transactions, fingerprints and acknowledgments belong to the pipeline."""
import json
import re
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.security import unified_code
from empire.core.time import mysql_time
from empire.features.financial_statements.contract import KINDS, digest, validate_rows
from empire.features.financial_statements.wire import pack_rows, unpack_rows
from empire.plugins.infra.collection_state import confirmed_page


class FinancialDataset:
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def __init__(self, kind):
        self.kind, self.table = kind, KINDS[kind][2]
        self.DATASETS = {kind + '.statement'}
        self.FINGERPRINT_NAMESPACE = 'ths_' + kind

    def normalize(self, envelope):
        p = envelope.raw_payload
        if set(p) != {'page', 'unit', 'rows', 'manifest'} or type(p['page']) is not int or not 1 <= p['page'] <= 15001:
            raise ValueError('财报消息结构无效')
        if p['unit'] == 'manifest':
            m = p['manifest']
            if (p['rows'] != [] or not isinstance(m, dict)
                    or set(m) != {'units', 'count', 'scope_hash', 'digest'}
                    or any(type(m[k]) is not int or not 1 <= m[k] <= 4500000 for k in ('units', 'count'))
                    or any(not isinstance(m[k], str) or not re.fullmatch('[0-9a-f]{64}', m[k])
                           for k in ('scope_hash', 'digest'))):
                raise ValueError('财报范围证明无效')
        else:
            if p['manifest'] is not None:
                raise ValueError('证券消息不能含最终证明')
            p = {**p, 'rows': unpack_rows(p['rows'])}
            validate_rows(self.kind, p['unit'], p['rows'])
        return {**p, 'row_count': len(p['rows'])}

    def canonical_payload(self, envelope, data):
        return {**{k: data[k] for k in ('page', 'unit', 'manifest')}, 'rows': pack_rows(data['rows'])}

    def fingerprint_plan(self, envelope, data):
        return self.FINGERPRINT_NAMESPACE, {data['unit']: (
            {'rows': data['rows'], 'manifest': data['manifest']},
            [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}

    def fingerprint_subset(self, data, identities):
        return {**data, 'write_unit': data['unit'] in identities}

    @staticmethod
    def state_unit(data):
        return data['unit']

    def write(self, conn, envelope, data):
        require_fixed_source(self.table, envelope.source)
        unit = data['unit']
        prior = data['archive_state'].get('units', {}).get(unit, {})
        if unit == 'manifest':
            prior = data['archive_state'].get('manifest', {})
        accepted = data.get('write_unit', True) and envelope.observed_at.isoformat() >= prior.get('observed_at', '')
        written = 0
        if accepted and unit != 'manifest':
            market, code = unit.split(':')
            params = dict(unified_code=unified_code(market, code))
            stored = {r['report_date'].isoformat(): dict(r) for r in conn.execute(text(
                f'SELECT report_date,payload,content_hash FROM {self.table} '
                'WHERE unified_code=:unified_code FOR UPDATE'), params).mappings()}
            for row in data['rows']:
                old = stored.get(row['report_date'])
                checksum = digest(row)
                if old and old['content_hash'] == checksum:
                    actual = json.loads(old['payload']) if isinstance(old['payload'], str) else old['payload']
                    if actual == row:
                        continue
                conn.execute(text(f'INSERT INTO {self.table} '
                    '(unified_code,report_date,payload,content_hash,version_observed_at) '
                    'VALUES (:unified_code,:report_date,:payload,:content_hash,:observed) '
                    'ON DUPLICATE KEY UPDATE payload=VALUES(payload),content_hash=VALUES(content_hash),'
                    'version_observed_at=VALUES(version_observed_at)'),
                    {**params, 'report_date': row['report_date'], 'payload': json.dumps(row, ensure_ascii=False),
                     'content_hash': checksum, 'observed': mysql_time(envelope.observed_at)})
                written += 1
        return dict(status='complete', row_count=data['row_count'], written_count=written,
                    confirmed=[unit] if accepted else [])

    def archive_state(self, envelope, data, outcome, previous):
        if data['unit'] not in outcome['confirmed']:
            return previous
        result = {**previous, 'contract_version': 1, 'progress': confirmed_page(envelope, data, previous)}
        observed = envelope.observed_at.isoformat()
        if data['unit'] == 'manifest':
            result['manifest'] = {**data['manifest'], 'observed_at': observed}
        else:
            result['units'] = {**previous.get('units', {}), data['unit']: {
                'observed_at': observed, 'dates': [r['report_date'] for r in data['rows']],
                'digest': digest(data['rows'])}}
        return result
