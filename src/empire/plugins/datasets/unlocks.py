"""One month/market transaction preserves list facts and shared detail groups."""
import re
from datetime import UTC, date

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.unlocks import (
    CONTRACT,
    DATASET,
    DETAIL_COLUMNS,
    JOB,
    PARENT_COLUMNS,
    PROJECT,
    canonical_number,
    digest,
    monthly_plan,
    pack,
    unpack,
    validate_unit,
)
from empire.core.time import mysql_time
from empire.plugins.infra.collection_state import confirmed_page

PARENT_TABLE, DETAIL_TABLE = 'restricted_share_unlock', 'restricted_share_unlock_detail'
TABLE_COLUMNS = {PARENT_TABLE: PARENT_COLUMNS, DETAIL_TABLE: DETAIL_COLUMNS}


def where_unit(unit):
    month, market = unit.split('|')
    start = date.fromisoformat(month)
    end = date(start.year + (start.month == 12), start.month % 12 + 1, 1)
    return 'unlock_date>=:start AND unlock_date<:end AND unified_code LIKE :market', {
        'start': month, 'end': end.isoformat(), 'market': '%.' + market}


def decode(record, columns):
    row = {k: record[k] for k in columns}
    row['unlock_date'] = row['unlock_date'].isoformat()
    for key in ('shares', 'total_shares'):
        if key in row:
            row[key] = canonical_number(row[key])
    return row


def list_digest(parents):
    return digest([{k: v for k, v in row.items() if k not in ('detail_status', 'detail_count')}
                   for row in parents])


def read_unit(conn, unit, *, lock=False):
    clause, params = where_unit(unit)
    output = []
    for table, columns, limit in ((PARENT_TABLE, PARENT_COLUMNS, 10000),
                                   (DETAIL_TABLE, DETAIL_COLUMNS, 100000)):
        records = conn.execute(text(f'SELECT * FROM {table} WHERE {clause} '
            f'ORDER BY record_key LIMIT {limit + 1}' + (' FOR UPDATE' if lock else '')), params).mappings().all()
        if len(records) > limit:
            raise ValueError('解禁正式单元读取超限')
        output.append((records, [decode(r, columns) for r in records]))
    return output


class UnlockDataset:
    DATASETS, PROJECT, JOB = {DATASET}, PROJECT, JOB
    FINGERPRINT_NAMESPACE = 'tdx_unlocks_v1'
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    @staticmethod
    def state_unit(data):
        return data['unit']

    def normalize(self, envelope):
        p = envelope.raw_payload
        if set(p) != {'page', 'unit', 'data', 'manifest'} or type(p['page']) is not int or not 1 <= p['page'] <= 10000:
            raise ValueError('解禁消息字段或页码无效')
        if p['unit'] == 'manifest':
            m = p['manifest']
            if (p['data'] is not None or not isinstance(m, dict)
                    or set(m) != {'start', 'end', 'units', 'count', 'details', 'digest'}):
                raise ValueError('解禁最终范围证明错误')
            units = monthly_plan(m['start'], m['end'])
            if (m['units'] != len(units) * 3 or any(type(m[k]) is not int or not 0 <= m[k] <= 10000000
                    for k in ('count', 'details')) or not isinstance(m['digest'], str)
                    or not re.fullmatch('[a-f0-9]{64}', m['digest'])):
                raise ValueError('解禁范围证明计数或摘要错误')
            parents, details = [], []
        else:
            if p['manifest'] is not None:
                raise ValueError('解禁业务单元不得冒充最终证明')
            parents, details = unpack(p['data'])
            validate_unit(p['unit'], parents, details)
        return {**p, 'parents': parents, 'details': details, 'row_count': len(parents) + len(details)}

    def canonical_payload(self, envelope, data):
        return {k: data[k] for k in ('page', 'unit', 'manifest')} | {
            'data': None if data['unit'] == 'manifest' else pack(data['parents'], data['details'])}

    def fingerprint_plan(self, envelope, data):
        content = {'parents': data['parents'], 'details': data['details'], 'manifest': data['manifest']}
        return self.FINGERPRINT_NAMESPACE, {data['unit']: (content, [
            envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}

    def fingerprint_subset(self, data, identities):
        return data

    def write(self, conn, envelope, data):
        for table in TABLE_COLUMNS:
            require_fixed_source(table, envelope.source)
        unit, previous = data['unit'], data['archive_state']
        prior = previous.get('manifest', {}) if unit == 'manifest' else previous.get('units', {}).get(unit, {})
        stamp = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
        outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
        if stamp < prior.get('observed_at', ''):
            return outcome
        if unit != 'manifest':
            existing = read_unit(conn, unit, lock=True)
            for (table, columns), (records, old_rows), new_rows in zip(TABLE_COLUMNS.items(), existing,
                    (data['parents'], data['details']), strict=True):
                old = {r['record_key']: (r, row) for r, row in zip(records, old_rows, strict=True)}
                new = {r['record_key']: r for r in new_rows}
                names = (*columns, 'content_hash', 'version_observed_at')
                changes = []
                for key, row in new.items():
                    stored, canonical = old.get(key, (None, None))
                    if stored and stored['version_observed_at'] > mysql_time(envelope.observed_at):
                        raise ValueError('解禁业务版本超过单位证明')
                    checksum = digest(row)
                    if canonical == row and stored['content_hash'] == checksum:
                        continue
                    changes.append({**row, 'content_hash': checksum,
                                    'version_observed_at': mysql_time(envelope.observed_at)})
                sql = text(f'INSERT INTO {table}({",".join(names)}) VALUES('
                    + ','.join(':' + k for k in names) + ') ON DUPLICATE KEY UPDATE '
                    + ','.join(k + '=VALUES(' + k + ')' for k in names if k not in ('record_key', 'group_key')))
                for offset in range(0, len(changes), 300):
                    conn.execute(sql, changes[offset:offset + 300])
                removed = sorted(old.keys() - new.keys())
                for offset in range(0, len(removed), 300):
                    keys = removed[offset:offset + 300]
                    conn.execute(text(f'DELETE FROM {table} WHERE record_key IN (' + ','.join(
                        ':k' + str(i) for i in range(len(keys))) + ')'),
                        {'k' + str(i): key for i, key in enumerate(keys)})
                outcome['written_count'] += len(changes) + len(removed)
        outcome['confirmed'] = [unit]
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if data['unit'] not in outcome['confirmed']:
            return previous
        result = {**previous, 'contract_version': CONTRACT,
                  'progress': confirmed_page(envelope, data, previous)}
        stamp = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
        if data['unit'] == 'manifest':
            result['manifest'] = {**data['manifest'], 'observed_at': stamp}
        else:
            result['units'] = {**previous.get('units', {}), data['unit']: dict(
                observed_at=stamp, count=len(data['parents']), details=len(data['details']), contract=CONTRACT,
                list_digest=list_digest(data['parents']), digest=digest([data['parents'], data['details']]),
                empty_groups=len({r['group_key'] for r in data['parents'] if r['detail_status'] == 'source_empty'}))}
        return result
