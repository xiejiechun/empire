"""One typed parameter/citation path, per-kind complete snapshot and version guard."""
from datetime import UTC
from decimal import Decimal

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.features.trading_rules.contract import (
    CITATION_COLUMNS,
    SOURCE,
    VALUE_COLUMNS,
    digest,
    payload,
    project,
)
from empire.plugins.infra.collection_state import confirmed_page

TABLES = {'trading_rule_value': {'record_key', *VALUE_COLUMNS},
          'trading_rule_citation': {'citation_key', *CITATION_COLUMNS}}
KEYS = {'trading_rule_value': ['record_key'], 'trading_rule_citation': ['citation_key']}


def canonical(row):
    result = dict(row)
    for key in ('effective_start', 'effective_end', 'published_date'):
        if result.get(key) is not None and hasattr(result[key], 'isoformat'):
            result[key] = result[key].isoformat()
    if result.get('number_value') is not None:
        result['number_value'] = format(result['number_value'], 'f').rstrip('0').rstrip('.') if '.' in format(result['number_value'], 'f') else str(result['number_value'])
        result['number_value'] = result['number_value'] or '0'
    for key in ('start_time', 'end_time'):
        if result.get(key) is not None and not isinstance(result[key], str):
            if hasattr(result[key], 'isoformat'):
                result[key] = result[key].isoformat()
            else:
                seconds = int(result[key].total_seconds())
                result[key] = f'{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}'
    return result


def read_snapshot(conn, kind, lock=False):
    rows = [canonical(r) for r in conn.execute(text('SELECT * FROM trading_rule_value WHERE kind=:kind ORDER BY record_key LIMIT 1001' + (' FOR UPDATE' if lock else '')), {'kind': kind}).mappings()]
    citations = [canonical(r) for r in conn.execute(text('SELECT DISTINCT c.* FROM trading_rule_citation c JOIN trading_rule_value v USING(citation_key) WHERE v.kind=:kind ORDER BY c.citation_key LIMIT 257'), {'kind': kind}).mappings()]
    return rows, citations


def canonical_payload(kind, value):
    normalized = payload(kind, value['rows'], value['citations'])
    # DECIMAL values have one representation across HTTP, SQL and Redis digests.
    normalized['rows'] = [canonical({**r, 'number_value': Decimal(r['number_value']) if r['number_value'] is not None else None}) for r in normalized['rows']]
    return normalized


class RuleDataset:
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def __init__(self, kind):
        self.kind, self.PROJECT = kind, project(kind)
        self.JOB = self.PROJECT + '-v1'
        self.DATASETS = {'rules.' + kind + '.complete'}
        self.FINGERPRINT_NAMESPACE = 'trading_' + kind + '_v1'

    def normalize(self, envelope):
        if envelope.source != SOURCE or envelope.business_key != self.kind or set(envelope.raw_payload) != {'page', 'rows', 'citations'} or envelope.raw_payload['page'] != 1:
            raise ValueError('交易规则消息身份、页号或字段无效')
        p = canonical_payload(self.kind, envelope.raw_payload)
        return {**p, 'row_count': len(p['rows'])}

    def canonical_payload(self, envelope, data):
        return {key: data[key] for key in ('page', 'rows', 'citations')}

    def fingerprint_plan(self, envelope, data):
        return self.FINGERPRINT_NAMESPACE, {self.kind: ([data['rows'], data['citations']], [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}

    def fingerprint_subset(self, data, identities):
        return data

    def write(self, conn, envelope, data):
        previous = data['archive_state']
        outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
        if envelope.observed_at.isoformat(timespec='microseconds') < previous.get('observed_at', ''):
            return outcome
        rows, citations = read_snapshot(conn, self.kind, lock=True)
        old_refs = {r['citation_key']: r for r in citations}
        changed_refs = [r for r in data['citations'] if old_refs.get(r['citation_key']) != r]
        existing_refs = {}
        if changed_refs:
            from sqlalchemy import bindparam
            statement = text('SELECT * FROM trading_rule_citation WHERE citation_key IN :keys FOR UPDATE').bindparams(bindparam('keys', expanding=True))
            existing_refs = {r['citation_key']: canonical(r) for r in conn.execute(statement, {'keys': [r['citation_key'] for r in changed_refs]}).mappings()}
        for r in changed_refs:
            existing = existing_refs.get(r['citation_key'])
            if not existing:
                conn.execute(text('INSERT INTO trading_rule_citation(citation_key,' + ','.join(CITATION_COLUMNS) + ') VALUES(:citation_key,' + ','.join(':' + k for k in CITATION_COLUMNS) + ')'), r)
                outcome['written_count'] += 1
            elif existing != r:
                # Only a source/contract-validated clause can repair damaged old metadata.
                conn.execute(text('UPDATE trading_rule_citation SET ' + ','.join(k + '=:' + k for k in CITATION_COLUMNS) + ' WHERE citation_key=:citation_key'), r)
                outcome['written_count'] += 1
        old = {r['record_key']: r for r in rows}
        new = {r['record_key']: r for r in data['rows']}
        if old.keys() - new.keys():
            raise ValueError('历史规则不能被当前集合删除；须先审查修订契约')
        changed = [r for key, r in new.items() if old.get(key) != r]
        if changed:
            conn.execute(text('INSERT INTO trading_rule_value(record_key,' + ','.join(VALUE_COLUMNS) + ') VALUES(:record_key,' + ','.join(':' + k for k in VALUE_COLUMNS) + ') ON DUPLICATE KEY UPDATE ' + ','.join(k + '=VALUES(' + k + ')' for k in VALUE_COLUMNS)), changed)
            outcome['written_count'] += len(changed)
        unused = old_refs.keys() - {r['citation_key'] for r in data['citations']}
        if unused:
            from sqlalchemy import bindparam
            statement = text('DELETE c FROM trading_rule_citation c LEFT JOIN trading_rule_value v USING(citation_key) WHERE c.citation_key IN :keys AND v.record_key IS NULL').bindparams(bindparam('keys', expanding=True))
            outcome['written_count'] += conn.execute(statement, {'keys': list(unused)}).rowcount
        outcome['confirmed'] = [self.kind]
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if not outcome['confirmed']:
            return previous
        return dict(observed_at=envelope.observed_at.isoformat(timespec='microseconds'),
            contract=1, digest=digest([data['rows'], data['citations']]), row_count=data['row_count'],
            progress=confirmed_page(envelope, data, previous))
