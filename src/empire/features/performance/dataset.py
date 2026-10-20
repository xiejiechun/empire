"""Typed business writes; complete source-unit proofs share collection_state."""
import re
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import CHINA, mysql_time
from empire.features.performance.contract import (
    FIELDS,
    SCHEMA_VERSION,
    columns,
    convert,
    day,
    digest,
    identity,
    pack,
    project,
    unpack,
    validate_rows,
)
from empire.features.performance.contract import (
    UNIT_KINDS as KINDS,
)
from empire.plugins.infra.collection_state import confirmed_page


def decode(kind, record):
    row = {key: record[key] for key in columns(kind)}
    for _, key, shape in FIELDS[kind]:
        if shape.startswith('date') and row[key] is not None:
            row[key] = row[key].isoformat()
        else:
            row[key] = convert(row[key], shape)
    return row


def unit_where(kind, unit):
    if kind == 'holder_count':
        return 'unified_code=:security', {'security': unit}
    period, market = unit.split('|')
    field = 'data_month' if kind == 'shareholder_changes' else 'report_date'
    return field + '=:period AND unified_code LIKE :market', {'period': period, 'market': '%.' + market}


def read_unit(conn, kind, unit, *, lock=False):
    table = KINDS[kind][1]
    where, params = unit_where(kind, unit)
    records = conn.execute(text(f'SELECT * FROM {table} WHERE {where} ORDER BY record_key LIMIT 80001'
                               + (' FOR UPDATE' if lock else '')), params).mappings().all()
    if len(records) > 80000:
        raise ValueError('业务单元SQL读取超限')
    return records


class PerformanceDataset:
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def __init__(self, kind):
        self.kind, self.table = kind, KINDS[kind][1]
        self.PROJECT, self.JOB = project(kind), project(kind) + '-v1'
        self.DATASETS = {kind + '.tdx_unit'}
        self.FINGERPRINT_NAMESPACE = 'tdx_' + kind

    def normalize(self, envelope):
        p = envelope.raw_payload
        if set(p) != {'page', 'unit', 'rows', 'manifest'} or type(p['page']) is not int or not 1 <= p['page'] <= 20000:
            raise ValueError('财报解读消息结构或顺序无效')
        if p['unit'] == 'manifest':
            m = p['manifest']
            expected = {'units', 'count', 'scope_hash', 'digest', 'latest'}
            if self.kind == 'shareholder_changes':
                expected.add('start')
            if p['rows'] != [] or not isinstance(m, dict) or set(m) != expected:
                raise ValueError('财报解读最终范围证明无效')
            if any(type(m[k]) is not int or not 0 <= m[k] <= 10000000 for k in ('units', 'count')):
                raise ValueError('范围证明计数无效')
            if any(not isinstance(m[k], str) or not re.fullmatch('[0-9a-f]{64}', m[k]) for k in ('scope_hash', 'digest')):
                raise ValueError('范围证明摘要无效')
            if not isinstance(m['latest'], str) or len(m['latest']) > 10:
                raise ValueError('范围证明上界无效')
            day(m['latest'])
            if self.kind == 'shareholder_changes':
                day(m['start'])
                if m['start'] > m['latest'] or m['start'][8:] != '01' or m['latest'][8:] != '01':
                    raise ValueError('持股变动指定月份范围无效')
            rows = []
        else:
            rows = unpack(self.kind, p['rows'])
            validate_rows(self.kind, p['unit'], rows)
            today = envelope.observed_at.astimezone(CHINA).date().isoformat()
            for row in rows:
                # Notice dates in forecast/quick/report are source declarations:
                # all three endpoints really expose tomorrow's notice today.
                for key in ('actual_date', 'statistics_date'):
                    if row.get(key) and row[key] > today:
                        raise ValueError('实际披露或统计日期超过采集时点')
            if p['manifest'] is not None:
                raise ValueError('业务单元不得伪装最终范围证明')
        return {**p, 'rows': rows, 'row_count': len(rows)}

    def canonical_payload(self, envelope, data):
        return {**{key: data[key] for key in ('page', 'unit', 'manifest')},
                'rows': [] if data['unit'] == 'manifest' else pack(self.kind, data['rows'])}

    def fingerprint_plan(self, envelope, data):
        return self.FINGERPRINT_NAMESPACE, {data['unit']: (
            {'rows': data['rows'], 'manifest': data['manifest']},
            [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}

    def fingerprint_subset(self, data, identities):
        return data

    @staticmethod
    def state_unit(data):
        return data['unit']

    def write(self, conn, envelope, data):
        require_fixed_source(self.table, envelope.source)
        unit, prior = data['unit'], data['archive_state']
        stamp = envelope.observed_at.isoformat(timespec='microseconds')
        old_proof = prior.get('manifest', {}) if unit == 'manifest' else prior.get('units', {}).get(unit, {})
        outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
        if stamp < old_proof.get('observed_at', ''):
            return outcome
        if unit != 'manifest':
            stored = {r['record_key']: r for r in read_unit(conn, self.kind, unit, lock=True)}
            changes = []
            for row in data['rows']:
                key, checksum = identity(self.kind, row), digest(row)
                old = stored.get(key)
                if old and old['version_observed_at'] > mysql_time(envelope.observed_at):
                    raise ValueError('单元证明落后于业务版本，禁止覆盖')
                if old and decode(self.kind, old) == row and old['content_hash'] == checksum:
                    continue
                changes.append({**row, 'record_key': key, 'content_hash': checksum,
                                'version_observed_at': mysql_time(envelope.observed_at)})
            names = ('record_key', *columns(self.kind), 'content_hash', 'version_observed_at')
            statement = text(f'INSERT INTO {self.table}({",".join(names)}) VALUES('
                + ','.join(':' + key for key in names) + ') ON DUPLICATE KEY UPDATE '
                + ','.join(key + '=VALUES(' + key + ')' for key in names if key != 'record_key'))
            for offset in range(0, len(changes), 300):
                conn.execute(statement, changes[offset:offset + 300])
            outcome['written_count'] = len(changes)
            if self.kind == 'shareholder_changes':
                current = {identity(self.kind, row) for row in data['rows']}
                removed = sorted(set(stored) - current)
                for offset in range(0, len(removed), 300):
                    keys = removed[offset:offset + 300]
                    conn.execute(text('DELETE FROM shareholder_change WHERE record_key IN ('
                        + ','.join(':k' + str(i) for i in range(len(keys))) + ')'),
                        {'k' + str(i): key for i, key in enumerate(keys)})
                outcome['written_count'] += len(removed)
        outcome['confirmed'] = [unit]
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if data['unit'] not in outcome['confirmed']:
            return previous
        result = {**previous, 'contract_version': SCHEMA_VERSION,
                  'progress': confirmed_page(envelope, data, previous)}
        observed = envelope.observed_at.isoformat(timespec='microseconds')
        if data['unit'] == 'manifest':
            result['manifest'] = {**data['manifest'], 'observed_at': observed}
        else:
            latest = max(data['rows'], key=lambda r: r.get('statistics_date', ''), default=None)
            result['units'] = {**previous.get('units', {}), data['unit']: {
                'observed_at': observed, 'count': len(data['rows']), 'digest': digest(data['rows']),
                'contract': SCHEMA_VERSION, 'latest_hash': digest(latest) if latest else None}}
        return result
