"""One complete security transaction with typed facts and bounded window proof."""
import re
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import CHINA, mysql_time
from empire.features.ths_capital.contract import (
    DATASET,
    JOB,
    PROJECT,
    SECTIONS,
    TABLES,
    digest,
    fields,
    number,
    validate,
)
from empire.features.ths_capital.transport import SCHEMA, pack, unpack
from empire.plugins.infra.collection_state import confirmed_page


def decode(table, row):
    result = {}
    for key, (_, kind) in fields(table).items():
        v = row[key]
        result[key] = None if v is None else number(format(v, 'f')) if kind == 'num' else bool(v) if kind == 'bool' else v.isoformat() if kind == 'date' else v
    return result


def read_window(conn, unit, *, lock=False):
    result = {}
    for table in TABLES:
        rows = conn.execute(text('SELECT * FROM ' + table + ' WHERE unified_code=:unit AND in_window=1 '
            'ORDER BY record_key LIMIT 10001' + (' FOR UPDATE' if lock else '')), dict(unit=unit)).mappings().all()
        if len(rows) > 10000:
            raise ValueError('资本运作当前窗口超限')
        result[table] = [decode(table, r) for r in rows]
    return result


class CapitalPageDataset:
    PROJECT, JOB, DATASETS = PROJECT, JOB, {DATASET}
    FINGERPRINT_NAMESPACE = 'ths_capital'
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def normalize(self, envelope):
        p = envelope.raw_payload
        if envelope.schema_version != SCHEMA or set(p) != {'page', 'unit', 'rows', 'availability', 'manifest'} or (
                type(p['page']) is not int or not 1 <= p['page'] <= 15001):
            raise ValueError('资本运作入队契约无效')
        p = {**p, 'rows': unpack(p['rows'])}
        if p['unit'] == 'manifest':
            m = p['manifest']
            if not isinstance(m, dict) or set(m) != {'units', 'count', 'scope_hash', 'digest', 'securities'} or (
                    type(m['units']) is not int or not 1 <= m['units'] <= 15000 or
                    type(m['count']) is not int or not 0 <= m['count'] <= 150000000 or
                    not isinstance(m['securities'], list) or len(m['securities']) != m['units'] or
                    m['securities'] != sorted(set(m['securities'])) or
                    any(not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', s) for s in m['securities']) or
                    m['scope_hash'] != digest(m['securities']) or not re.fullmatch('[a-f0-9]{64}', m['digest'])):
                raise ValueError('资本运作最终证券集合证明无效')
            if p['rows'] != {t: [] for t in TABLES} or p['availability']:
                raise ValueError('资本运作范围标记不得带业务正文')
        else:
            validate(p['unit'], p['rows'], p['availability'], today=envelope.observed_at.astimezone(CHINA).date())
            if p['manifest'] is not None:
                raise ValueError('资本运作业务单元不得带范围标记')
        if envelope.business_key != p['unit']:
            raise ValueError('资本运作消息业务键不符')
        return {**p, 'row_count': sum(map(len, p['rows'].values()))}

    def canonical_payload(self, envelope, data):
        return {**{k: data[k] for k in ('page', 'unit', 'availability', 'manifest')}, 'rows': pack(data['rows'])}

    def fingerprint_plan(self, envelope, data):
        return self.FINGERPRINT_NAMESPACE, {data['unit']: (
            {k: data[k] for k in ('rows', 'availability', 'manifest')},
            [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}

    def fingerprint_subset(self, data, identities):
        return data

    @staticmethod
    def state_unit(data):
        return data['unit']

    def write(self, conn, envelope, data):
        require_fixed_source(TABLES[0], envelope.source)
        unit, previous = data['unit'], data['archive_state']
        old = previous.get('manifest', {}) if unit == 'manifest' else previous.get('units', {}).get(unit, {})
        observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
        result = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
        if observed < old.get('observed_at', ''):
            return result
        if unit != 'manifest':
            stamp = mysql_time(envelope.observed_at)
            # Compare the actual SQL body on cold cache, including damaged fields.
            # An observed version is a transport guard, never a source revision ID.
            for table in TABLES:
                fetched = data['rows'][table]
                current = conn.execute(text('SELECT record_key FROM ' + table +
                    ' WHERE unified_code=:unit AND in_window=1 FOR UPDATE'), dict(unit=unit)).scalars().all()
                expected = {r['record_key'] for r in fetched}
                for start in range(0, len(fetched), 100):
                    group = fetched[start:start + 100]
                    params = {'k' + str(i): r['record_key'] for i, r in enumerate(group)}
                    placeholders = ','.join(':' + k for k in params)
                    old_rows = conn.execute(text('SELECT * FROM ' + table + ' WHERE record_key IN (' +
                        placeholders + ') FOR UPDATE'), params).mappings().all()
                    existing = {r['record_key']: r for r in old_rows}
                    changed = []
                    for row in group:
                        head = existing.get(row['record_key'])
                        if head and head['version_observed_at'] > stamp:
                            raise ValueError('资本运作单元版本混合，拒绝覆盖并回滚')
                        if head and head['in_window'] and decode(table, head) == row and head['content_hash'] == digest(row):
                            continue
                        changed.append({**row, 'in_window': True, 'content_hash': digest(row), 'version_observed_at': stamp})
                    if changed:
                        names = tuple(changed[0])
                        conn.execute(text('INSERT INTO ' + table + '(' + ','.join(names) + ') VALUES(' +
                            ','.join(':' + n for n in names) + ') ON DUPLICATE KEY UPDATE ' +
                            ','.join(n + '=VALUES(' + n + ')' for n in names if n != 'record_key')), changed)
                        result['written_count'] += len(changed)
                gone = sorted(set(current) - expected)
                for start in range(0, len(gone), 100):
                    params = {'k' + str(i): k for i, k in enumerate(gone[start:start + 100])}
                    conn.execute(text('UPDATE ' + table + ' SET in_window=0 WHERE record_key IN (' +
                        ','.join(':' + k for k in params) + ')'), params)
                    result['written_count'] += len(params)
        result['confirmed'] = [unit]
        return result

    def archive_state(self, envelope, data, outcome, previous):
        unit = data['unit']
        if unit not in outcome['confirmed']:
            return previous
        observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
        result = {**previous, 'contract_version': 1, 'progress': confirmed_page(envelope, data, previous)}
        if unit == 'manifest':
            result['manifest'] = {**data['manifest'], 'observed_at': observed}
        else:
            proof = dict(observed_at=observed, digest=digest(data['rows']), count=data['row_count'],
                         availability=data['availability'], contract=1,
                         sections={section: digest({t: [r for r in values if r['section'] == section]
                            for t, values in data['rows'].items()}) for section in SECTIONS})
            result['units'] = {**previous.get('units', {}), unit: proof}
        return result
