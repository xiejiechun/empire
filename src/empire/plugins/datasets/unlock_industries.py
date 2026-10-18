"""Replace only one complete month; preserve months leaving the source window."""
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.unlock_industries import (
    COLUMNS,
    DATASET,
    JOB,
    NUMBERS,
    PROJECT,
    TABLE,
    basis,
    canonical_number,
    digest,
    month,
    validate,
    version,
)
from empire.core.time import CHINA, mysql_time
from empire.plugins.infra.collection_state import confirmed_page

TABLE_COLUMNS = {TABLE: COLUMNS}


def decode(record):
    row = {k: record[k] for k in COLUMNS}
    for key in ('unlock_month', 'basis_date'):
        row[key] = row[key].isoformat()
    for key in NUMBERS:
        row[key] = canonical_number(row[key])
    return row


def read_month(conn, unit, *, lock=False):
    records = conn.execute(text(f'SELECT * FROM {TABLE} WHERE unlock_month=:month '
        'ORDER BY industry LIMIT 501' + (' FOR UPDATE' if lock else '')), {'month': month(unit)}).mappings().all()
    if len(records) > 500:
        raise ValueError('解禁行业月读取超限')
    return records, [decode(r) for r in records]


class UnlockIndustryDataset:
    DATASETS, PROJECT, JOB = {DATASET}, PROJECT, JOB
    FINGERPRINT_NAMESPACE = 'tdx_unlock_industries_v1'
    FINGERPRINT_VERSION = ArchiveVersion(('utc', 'utc'), observed_index=1, source_indices=(0,))

    def normalize(self, envelope):
        p = envelope.raw_payload
        if (set(p) != {'page', 'unit', 'basis_date', 'rows', 'manifest'} or type(p['page']) is not int
                or not 1 <= p['page'] <= 121):
            raise ValueError('解禁行业消息契约错误')
        basis(p['basis_date'])
        if p['unit'] == 'manifest':
            m = p['manifest']
            if (p['rows'] != [] or not isinstance(m, dict) or set(m) != {'months', 'count', 'digest'}
                    or not isinstance(m['months'], list) or not 1 <= len(m['months']) <= 120
                    or m['months'] != sorted(set(m['months']))
                    or type(m['count']) is not int or not 0 <= m['count'] <= 60000
                    or not isinstance(m['digest'], str) or len(m['digest']) != 64):
                raise ValueError('解禁行业目录完成证明错误')
            for unit in m['months']:
                month(unit)
        else:
            if p['manifest'] is not None:
                raise ValueError('解禁行业月与完成证明冲突')
            validate(p['unit'], p['basis_date'], p['rows'])
        if envelope.business_key != p['unit']:
            raise ValueError('解禁行业消息身份不一致')
        return {**p, 'row_count': len(p['rows'])}

    def canonical_payload(self, envelope, data):
        return {k: data[k] for k in ('page', 'unit', 'basis_date', 'rows', 'manifest')}

    def fingerprint_plan(self, envelope, data):
        return self.FINGERPRINT_NAMESPACE, {data['unit']: (
            {k: data[k] for k in ('basis_date', 'rows', 'manifest')}, version(data['basis_date'], envelope.observed_at))}

    def fingerprint_subset(self, data, identities):
        return data

    def write(self, conn, envelope, data):
        require_fixed_source(TABLE, envelope.source)
        unit, previous = data['unit'], data['archive_state']
        prior = previous.get('manifest', {}) if unit == 'manifest' else previous.get('units', {}).get(unit, {})
        incoming = version(data['basis_date'], envelope.observed_at)
        outcome = dict(status='complete', row_count=len(data['rows']), written_count=0, confirmed=[])
        if prior.get('version') and self.FINGERPRINT_VERSION.compare(incoming, prior['version']) < 0:
            return outcome
        if unit != 'manifest':
            records, rows = read_month(conn, unit, lock=True)
            old = {r['industry']: (record, r) for record, r in zip(records, rows, strict=True)}
            new = {r['industry']: r for r in data['rows']}
            changes = []
            for record in records:
                old_version = version(record['basis_date'].isoformat(), record['version_observed_at'].replace(tzinfo=CHINA))
                if self.FINGERPRINT_VERSION.compare(incoming, old_version) < 0:
                    raise ValueError('解禁行业业务版本超过单位证明，拒绝覆盖')
            for key, row in new.items():
                record, content = old.get(key, (None, None))
                checksum = digest(row)
                if row == content and record['content_hash'] == checksum:
                    continue
                changes.append({**row, 'content_hash': checksum, 'version_observed_at': mysql_time(envelope.observed_at)})
            names = (*COLUMNS, 'content_hash', 'version_observed_at')
            sql = text(f'INSERT INTO {TABLE}({",".join(names)}) VALUES(' + ','.join(':' + k for k in names)
                + ') ON DUPLICATE KEY UPDATE ' + ','.join(k + '=VALUES(' + k + ')' for k in names
                    if k not in ('unlock_month', 'industry')))
            if changes:
                conn.execute(sql, changes)
            removed = sorted(old.keys() - new.keys())
            if removed:
                conn.execute(text(f'DELETE FROM {TABLE} WHERE unlock_month=:month AND industry=:industry'),
                             [dict(month=unit, industry=key) for key in removed])
            outcome['written_count'] = len(changes) + len(removed)
        outcome['confirmed'] = [unit]
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if not outcome['confirmed']:
            return previous
        result = {**previous, 'contract_version': 1, 'progress': confirmed_page(envelope, data, previous)}
        stamp = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
        proof = dict(basis_date=data['basis_date'], observed_at=stamp, version=version(data['basis_date'], envelope.observed_at))
        if data['unit'] == 'manifest':
            result['manifest'] = {**data['manifest'], **proof}
        else:
            result['units'] = {**previous.get('units', {}), data['unit']: {
                **proof, 'count': len(data['rows']), 'digest': digest(data['rows']), 'contract': 1}}
        if len(result.get('units', {})) > 2600:
            raise ValueError('解禁行业保留月份证明超限')
        return result
