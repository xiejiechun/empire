"""Complete holder reports use one typed parent/member transaction."""
import re
from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import CHINA, mysql_time
from empire.features.holders.contract import (
    KINDS,
    MEMBER_FIELDS,
    REPORT_FIELDS,
    digest,
    number,
    project,
    report_key,
    validate,
    validate_gaps,
)
from empire.plugins.infra.collection_state import confirmed_page

NUMBERS = {'total_quantity', 'total_ratio', 'quantity', 'ratio', 'change_quantity', 'pledge_ratio'}


def decode(row, fields):
    return {k: (number(format(row[k], 'f'), signed=True) if k in NUMBERS and row[k] is not None else
                row[k].isoformat() if k == 'report_date' else row[k]) for k in fields}


def read_reports(conn, keys, *, lock=False):
    if not keys:
        return []
    if len(keys) > 10:
        raise ValueError('报告详情批读超限')
    placeholders = ','.join(':k' + str(i) for i in range(len(keys)))
    params = {'k' + str(i): k for i, k in enumerate(keys)}
    heads = conn.execute(text('SELECT * FROM holder_report WHERE report_key IN (' + placeholders + ')'
                              + (' FOR UPDATE' if lock else '')), params).mappings().all()
    members = conn.execute(text('SELECT * FROM holder_member WHERE report_key IN (' + placeholders +
        ') ORDER BY report_key,member_group,seq LIMIT 4001'), params).mappings().all()
    if len(members) > 4000:
        raise ValueError('报告明细批读超限')
    grouped = {key: [] for key in keys}
    for member in members:
        grouped[member['report_key']].append(decode(member, MEMBER_FIELDS))
    values = []
    for head in heads:
        row = {**decode(head, REPORT_FIELDS), 'members': grouped[head['report_key']]}
        # Source ordering groups current first; SQL group lexical order matches it.
        if (digest(row) != head['content_hash'] or report_key(row) != head['report_key'] or
                head['member_count'] != sum(m['member_group'] == 'current' for m in row['members']) or
                head['exit_count'] != sum(m['member_group'] == 'exited' for m in row['members'])):
            raise ValueError('持有人报告正文与完整性摘要不符')
        values.append(row)
    return sorted(values, key=lambda r: (r['report_date'], r['instrument_key'], r['report_type']))


class HolderDataset:
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def __init__(self):
        self.PROJECT = project('top_holders')
        self.JOB, self.DATASETS = self.PROJECT + '-v1', {'holders.reports'}
        self.FINGERPRINT_NAMESPACE = 'ths_holders'

    def normalize(self, envelope):
        if envelope.schema_version != 5:
            raise ValueError('持有人消息schema版本无效；须显式重建')
        p = envelope.raw_payload
        if set(p) != {'page', 'unit', 'reports', 'manifest', 'gaps'} or type(p['page']) is not int or not 1 <= p['page'] <= 15001:
            raise ValueError('持有人消息契约无效')
        if not isinstance(p['reports'], dict) or set(p['reports']) != set(KINDS):
            raise ValueError('持有人消息须包含三个栏目')
        validate_gaps(p['gaps'])
        if p['unit'] == 'manifest':
            m = p['manifest']
            if p['gaps'] or any(p['reports'].values()) or not isinstance(m, dict) or set(m) != {'units', 'count', 'scope_hash', 'digest', 'securities', 'kinds'}:
                raise ValueError('持有人范围证明无效')
            if not isinstance(m['kinds'], dict) or set(m['kinds']) != set(KINDS) or any(
                    not isinstance(v, dict) or set(v) != {'count', 'digest'} or type(v['count']) is not int or
                    not 0 <= v['count'] <= 1500000 or not isinstance(v['digest'], str) or
                    not re.fullmatch('[0-9a-f]{64}', v['digest']) for v in m['kinds'].values()) or (
                    sum(v['count'] for v in m['kinds'].values()) != m['count']):
                raise ValueError('持有人三栏范围证明无效')
            if any(type(m[k]) is not int or not 0 <= m[k] <= limit for k, limit in
                   (('units', 15000), ('count', 4500000))) or any(
                    not isinstance(m[k], str) or not re.fullmatch('[0-9a-f]{64}', m[k]) for k in ('scope_hash', 'digest')):
                raise ValueError('持有人范围证明字段无效')
            securities = m['securities']
            if not isinstance(securities, list) or not 1 <= len(securities) <= 15000 or any(
                    not isinstance(k, str) or not re.fullmatch(r'\d{6}\.(SH|SZ|BJ)', k) for k in securities) or (
                    securities != sorted(set(securities)) or len(securities) != m['units'] or digest(securities) != m['scope_hash']):
                raise ValueError('持有人范围证券集合无效')
        else:
            for kind, rows in p['reports'].items():
                validate(kind, p['unit'], rows, today=envelope.observed_at.astimezone(CHINA).date())
            if p['manifest'] is not None:
                raise ValueError('持有人单元不得带最终范围证明')
        return {**p, 'row_count': sum(len(r['members']) for rows in p['reports'].values() for r in rows)}

    def canonical_payload(self, envelope, data):
        return {k: data[k] for k in ('page', 'unit', 'reports', 'manifest', 'gaps')}

    def fingerprint_plan(self, envelope, data):
        content = {'reports': data['reports'], 'manifest': data['manifest']}
        if data['gaps']:
            content['gaps'] = data['gaps']
        return self.FINGERPRINT_NAMESPACE, {data['unit']: (
            content,
            [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}

    def fingerprint_subset(self, data, identities):
        return data

    @staticmethod
    def state_unit(data):
        return data['unit']

    def write(self, conn, envelope, data):
        require_fixed_source('holder_report', envelope.source)
        unit, previous = data['unit'], data['archive_state']
        old = previous.get('manifest', {}) if unit == 'manifest' else previous.get('units', {}).get(unit, {})
        observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
        outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
        if observed < old.get('observed_at', ''):
            return outcome
        stamp = mysql_time(envelope.observed_at)
        for report in (r for kind in KINDS for r in data['reports'][kind]):
            key, checksum = report_key(report), digest(report)
            head = conn.execute(text('SELECT content_hash,version_observed_at FROM holder_report '
                'WHERE report_key=:key FOR UPDATE'), {'key': key}).mappings().first()
            if head and head['version_observed_at'] > stamp:
                # Old observations are rejected as an entire security window.
                if outcome['written_count']:
                    raise ValueError('报告版本混合，回滚本单元')
                return outcome
            if head and head['content_hash'] == checksum:
                # Re-read members on cold SQL to detect/repair required-field damage.
                try:
                    if read_reports(conn, [key]) == [report]:
                        continue
                except ValueError:
                    pass
            params = {k: report[k] for k in REPORT_FIELDS}
            params.update(report_key=key, content_hash=checksum, version_observed_at=stamp,
                          member_count=sum(m['member_group'] == 'current' for m in report['members']),
                          exit_count=sum(m['member_group'] == 'exited' for m in report['members']))
            names = tuple(params)
            conn.execute(text('INSERT INTO holder_report(' + ','.join(names) + ') VALUES(' +
                ','.join(':' + n for n in names) + ') ON DUPLICATE KEY UPDATE ' +
                ','.join(n + '=VALUES(' + n + ')' for n in names if n != 'report_key')), params)
            if head:
                conn.execute(text('DELETE FROM holder_member WHERE report_key=:key'), {'key': key})
            names = ('report_key', *MEMBER_FIELDS)
            conn.execute(text('INSERT INTO holder_member(' + ','.join(names) + ') VALUES(' +
                ','.join(':' + n for n in names) + ')'), [{**m, 'report_key': key} for m in report['members']])
            outcome['written_count'] += len(report['members']) + 1
        outcome['confirmed'] = [unit]
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if data['unit'] not in outcome['confirmed']:
            return previous
        result = {**previous, 'contract_version': 4, 'progress': confirmed_page(envelope, data, previous)}
        observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
        if data['unit'] == 'manifest':
            result['manifest'] = {**data['manifest'], 'observed_at': observed}
        else:
            proof = dict(observed_at=observed, count=sum(map(len, data['reports'].values())),
                         digest=digest(data['reports']), contract=4, source_gaps=data['gaps'],
                         source_gaps_digest=digest(data['gaps']),
                         kinds={kind: dict(observed_at=observed, count=len(rows), digest=digest(rows),
                            report_keys=[report_key(r) for r in rows], contract=4,
                            availability=('source_gap' if any(g['kind'] == kind for g in data['gaps']) else
                                          'available' if rows else 'not_published'))
                            for kind, rows in data['reports'].items()})
            result['units'] = {**previous.get('units', {}), data['unit']: proof}
        return result
