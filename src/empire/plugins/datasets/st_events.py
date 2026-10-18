"""Typed ST-event snapshots per category and market, one canonical write path."""
from datetime import UTC, date

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.st_events import (
    COLUMNS,
    MARKETS,
    digest,
    identity,
    pack_rows,
    project,
    unpack_rows,
    validate_rows,
)
from empire.core.time import CHINA
from empire.plugins.infra.collection_state import confirmed_page

TABLE = 'security_st_event'
TABLES = {TABLE: {'event_kind', 'record_key', *COLUMNS}}
KEYS = {TABLE: ['event_kind', 'record_key']}
CONTRACT = 1


def read_rows(conn, kind, market=None, *, lock=False, include_keys=False):
    where = 'event_kind=:kind'
    if market:
        where += ' AND unified_code LIKE :market'
    records = conn.execute(text(f'SELECT record_key,{",".join(COLUMNS)} FROM {TABLE} WHERE {where} '
        'ORDER BY record_key LIMIT 30001' + (' FOR UPDATE' if lock else '')),
        {'kind': kind, 'market': '%.' + (market or '')}).all()
    rows = [[r[1], r[2].isoformat(), *r[3:]] for r in records]
    return (rows, sum(r[0] != identity(row) for r, row in zip(records, rows, strict=True))) if include_keys else rows


class StDataset:
    FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)

    def __init__(self, kind):
        self.kind = kind
        self.DATASETS = {'st.' + kind + '.market'}
        self.FINGERPRINT_NAMESPACE = 'tdx_st_' + kind + '_v1'
        self.PROJECT = project(kind)
        self.JOB = self.PROJECT + '-v1'

    def normalize(self, envelope):
        p = envelope.raw_payload
        if set(p) != {'page', 'market', 'through', 'rows', 'industries', 'source_count'}:
            raise ValueError('ST事件消息字段不符')
        p = {**p, 'rows': unpack_rows(p['rows'], p['industries'])}
        if p['market'] not in MARKETS or type(p['page']) is not int or p['page'] != MARKETS.index(p['market']) + 1:
            raise ValueError('ST事件市场消息顺序无效')
        if (not isinstance(p['through'], str) or date.fromisoformat(p['through']).isoformat() != p['through']
                or not '1990-01-01' <= p['through'] <= envelope.observed_at.astimezone(CHINA).date().isoformat()
                or any(r[1] > p['through'] for r in p['rows'])):
            raise ValueError('ST事件消息日期范围无效')
        count = validate_rows(self.kind, p['market'], p['rows'])
        if type(p['source_count']) is not int or count != p['source_count']:
            raise ValueError('ST事件来源出现次数与消息证明不符')
        return {**p, 'row_count': len(p['rows'])}

    def canonical_payload(self, envelope, data):
        return {**{k: data[k] for k in ('page', 'market', 'through', 'source_count')}, **pack_rows(data['rows'])}

    def fingerprint_plan(self, envelope, data):
        return self.FINGERPRINT_NAMESPACE, {data['market']: (data['rows'], [
            envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}

    def fingerprint_subset(self, data, identities):
        return data

    def write(self, conn, envelope, data):
        require_fixed_source(TABLE, envelope.source)
        stamp = envelope.observed_at.isoformat(timespec='microseconds')
        previous = data['archive_state'].get('markets', {}).get(data['market'], {})
        outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
        if stamp < previous.get('observed_at', ''):
            return outcome
        records = conn.execute(text(f'SELECT record_key,{",".join(COLUMNS)} FROM {TABLE} '
            'WHERE event_kind=:kind AND unified_code LIKE :market LIMIT 30001 FOR UPDATE'),
            {'kind': self.kind, 'market': '%.' + data['market']}).all()
        old = {r[0]: [r[1], r[2].isoformat(), *r[3:]] for r in records}
        new = {identity(row): row for row in data['rows']}
        removed = old.keys() - new.keys()
        if removed:
            conn.execute(text(f'DELETE FROM {TABLE} WHERE event_kind=:kind AND record_key=:key'),
                         [{'kind': self.kind, 'key': key} for key in removed])
        changed = [dict(zip(COLUMNS, row, strict=True), event_kind=self.kind, record_key=key)
                   for key, row in new.items() if old.get(key) != row]
        for offset in range(0, len(changed), 500):
            conn.execute(text(f'INSERT INTO {TABLE}(event_kind,record_key,{",".join(COLUMNS)}) '
                f'VALUES(:event_kind,:record_key,{",".join(":" + k for k in COLUMNS)}) '
                'ON DUPLICATE KEY UPDATE unified_code=VALUES(unified_code),event_date=VALUES(event_date),'
                'old_name=VALUES(old_name),new_name=VALUES(new_name),source_occurrences=VALUES(source_occurrences),'
                'csrc_industry=VALUES(csrc_industry),tdx_industry=VALUES(tdx_industry),reason=VALUES(reason)'), changed[offset:offset + 500])
        outcome.update(written_count=len(removed) + len(changed), confirmed=[data['market']])
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if not outcome['confirmed']:
            return previous
        markets = dict(previous.get('markets', {}))
        markets[data['market']] = dict(observed_at=envelope.observed_at.isoformat(timespec='microseconds'),
            through=data['through'], digest=digest(data['rows']), row_count=data['row_count'],
            source_count=data['source_count'], contract=CONTRACT)
        return dict(markets=markets, progress=confirmed_page(envelope, data, previous))
