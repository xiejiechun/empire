"""Three independent dataset mappings using the same event-storage mechanics."""
import json
import re
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.core.time import mysql_time
from empire.plugins.datasets.capital_actions import KINDS, SCHEMA_VERSIONS, digest, validate_rows
from empire.plugins.infra.collection_state import confirmed_page


def chain(previous, unit, rows):
    return digest([previous, unit, digest(rows), len(rows)])


class CapitalDataset:
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def __init__(self, kind):
        self.kind, self.table = kind, KINDS[kind][1]
        self.DATASETS = {kind + '.unit'}
        self.FINGERPRINT_NAMESPACE = kind

    def normalize(self, envelope):
        p = envelope.raw_payload
        if set(p) != {'page', 'unit', 'rows', 'manifest'}:
            raise ValueError('增发送配批次结构无效')
        if type(p['page']) is not int or not 1 <= p['page'] <= 20000:
            raise ValueError('增发送配批次序号无效')
        if p['unit'] == 'manifest':
            m = p['manifest']
            if p['rows'] != [] or not isinstance(m, dict) or set(m) != {'units', 'count', 'scope_hash', 'digest'}:
                raise ValueError('最终范围证明无效')
            if any(type(m[k]) is not int or not 0 <= m[k] <= 1000000 for k in ('units', 'count')):
                raise ValueError('范围证明计数无效')
            if any(not isinstance(m[k], str) or not re.fullmatch('[0-9a-f]{64}', m[k]) for k in ('scope_hash', 'digest')):
                raise ValueError('范围证明摘要无效')
        else:
            if not isinstance(p['unit'], str) or not re.fullmatch('(SH|SZ|BJ):[0-9]{6}', p['unit']) or p['manifest'] is not None:
                raise ValueError('证券单元无效')
            validate_rows(self.kind, p['unit'], p['rows'])
        return {**p, 'row_count': len(p['rows'])}

    def canonical_payload(self, envelope, data):
        return {k: data[k] for k in ('page', 'unit', 'rows', 'manifest')}

    def fingerprint_plan(self, envelope, data):
        return self.kind, {data['unit']: (
            {'rows': data['rows'], 'manifest': data['manifest']},
            [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}

    def fingerprint_subset(self, data, identities):
        return {**data, 'write_unit': data['unit'] in identities}

    def write(self, conn, envelope, data):
        unit, previous = data['unit'], data['archive_state']
        observed = envelope.observed_at.isoformat(timespec='microseconds')
        prior = previous.get('units', {}).get(unit, {}) if unit != 'manifest' else previous.get('manifest', {})
        accepted = data.get('write_unit', True) and observed >= prior.get('observed_at', '')
        written = 0
        if accepted and unit != 'manifest':
            market, code = unit.split(':')
            params = dict(source=envelope.source, market=market, code=code)
            old = {r['record_key']: dict(r) for r in conn.execute(text(
                f'SELECT * FROM {self.table} '
                'WHERE source=:source AND market=:market AND code=:code FOR UPDATE'), params).mappings()}
            for row in data['rows']:
                checksum = digest(row)
                stored = old.get(row['record_key'])
                if stored:
                    payload = json.loads(stored['payload']) if isinstance(stored['payload'], str) else stored['payload']
                    actual = {k: stored[k] for k in ('record_key', 'market', 'code', 'name')}
                    actual.update(data=payload, event_date=stored['event_date'].isoformat() if stored['event_date'] else None)
                    if actual == row and stored['content_hash'] == checksum:
                        continue
                values = {**params, **{k: row[k] for k in ('record_key', 'name', 'event_date')},
                          'payload': json.dumps(row['data'], ensure_ascii=False, sort_keys=True),
                          'content_hash': checksum, 'version_observed_at': mysql_time(envelope.observed_at)}
                conn.execute(text(f'INSERT INTO {self.table} '
                    '(source,record_key,market,code,name,event_date,payload,content_hash,version_observed_at) '
                    'VALUES (:source,:record_key,:market,:code,:name,:event_date,:payload,:content_hash,:version_observed_at) '
                    'ON DUPLICATE KEY UPDATE name=VALUES(name),event_date=VALUES(event_date),payload=VALUES(payload),'
                    'content_hash=VALUES(content_hash),version_observed_at=VALUES(version_observed_at)'), values)
                written += 1
        return dict(status='complete', row_count=data['row_count'], written_count=written,
                    confirmed=[unit] if accepted else [])

    def archive_state(self, envelope, data, outcome, previous):
        result = {**previous, 'contract_version': SCHEMA_VERSIONS[self.kind],
                  'progress': confirmed_page(envelope, data, previous)}
        if data['unit'] not in outcome['confirmed']:
            return previous
        observed = envelope.observed_at.isoformat(timespec='microseconds')
        if data['unit'] == 'manifest':
            result['manifest'] = {**data['manifest'], 'observed_at': observed}
        else:
            result['units'] = {**previous.get('units', {}), data['unit']: {
                'observed_at': observed, 'count': len(data['rows']), 'digest': digest(data['rows'])}}
        return result
