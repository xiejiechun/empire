"""Complete source years and validated tail merges on the unified archive path."""
from datetime import UTC
from decimal import Decimal

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import mysql_time
from empire.features.fx.contract import (
    DAILY_JOB,
    DATASET,
    FIELDS,
    SOURCE,
    TABLES,
    day,
    digest,
    identity,
    symbol,
    validate_rows,
)
from empire.features.fx.source import closed_through
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {DATASET}
FINGERPRINT_NAMESPACE = 'ths_fx_v1'
FINGERPRINT_VERSION = ArchiveVersion(('utc',), observed_index=0)


def normalize(envelope):
    p = envelope.raw_payload
    if (envelope.job_key != DAILY_JOB or envelope.source != SOURCE or envelope.dataset != DATASET
            or set(p) != {'page', 'code', 'year', 'mode', 'source_count', 'start', 'end', 'rows'}
            or type(p['page']) is not int or not 1 <= p['page'] <= 10000
            or type(p['year']) is not int or not 1900 <= p['year'] <= 2100
            or p['mode'] not in ('full', 'recent') or type(p['source_count']) is not int
            or not 1 <= p['source_count'] <= 366):
        raise ValueError('汇率日线归档契约无效；实时任务不得发布归档消息')
    code = symbol(p['code'])
    ident = f"{code}:{p['year']}"
    rows = validate_rows(p['rows'], p['year'])
    if (envelope.business_key != ident or day(p['start']) > rows[0][0]
            or rows[-1][0] > day(p['end']) or p['end'] > closed_through(envelope.observed_at)
            or len(rows) > p['source_count']
            or p['mode'] == 'full' and (len(rows) != p['source_count']
                or p['start'][:4] == str(p['year']) and rows[0][0] != p['start'])):
        raise ValueError('汇率年度集合、日期或已结束边界不符')
    return {**p, 'identity': ident, 'row_count': len(rows)}


def canonical_payload(envelope, data):
    return {k: data[k] for k in envelope.raw_payload}


def fingerprint_plan(envelope, data):
    content = {k: data[k] for k in ('code', 'year', 'mode', 'source_count', 'rows')}
    return FINGERPRINT_NAMESPACE, {data['identity']: (content,
        [envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')])}


def fingerprint_subset(data, identities):
    return data


def sql_rows(conn, code, year):
    rows = conn.execute(text('SELECT trade_date,open,high,low,close FROM fx_daily_price '
        'WHERE unified_code=:code AND trade_date BETWEEN :start AND :end ORDER BY trade_date'),
        dict(code=identity(code), start=f'{year}-01-01', end=f'{year}-12-31')).all()
    return [[r[0].isoformat(), *[format(Decimal(v).normalize(), 'f') for v in r[1:]]] for r in rows]


def write(conn, envelope, data):
    for table in TABLES:
        require_fixed_source(table, envelope.source)
    code, year, ident = data['code'], data['year'], data['identity']
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    outcome = dict(status='complete', row_count=data['row_count'], written_count=0, confirmed=[])
    if observed < data['archive_state'].get('versions', {}).get(ident, ''):
        return outcome
    head = conn.execute(text('SELECT * FROM fx_price_year WHERE unified_code=:code '
        'AND quote_year=:year FOR UPDATE'), dict(code=identity(code), year=year)).mappings().first()
    if head and mysql_time(envelope.observed_at) < head['version_observed_at']:
        return outcome
    old = {r[0]: r for r in sql_rows(conn, code, year)}
    incoming = {r[0]: r for r in data['rows']}
    new = incoming if data['mode'] == 'full' else {**old, **incoming}
    if len(new) != data['source_count'] or data['mode'] == 'recent' and not head:
        raise ValueError('汇率近期合并不能证明完整年度，须补取完整年度')
    removed = [dict(code=identity(code), day=d) for d in old.keys() - new.keys()]
    changed = [dict(code=identity(code), day=d, **dict(zip(FIELDS, r[1:], strict=True)))
               for d, r in new.items() if old.get(d) != r]
    if removed:
        conn.execute(text('DELETE FROM fx_daily_price WHERE unified_code=:code AND trade_date=:day'), removed)
    if changed:
        conn.execute(text('INSERT INTO fx_daily_price(unified_code,trade_date,open,high,low,close) '
            'VALUES(:code,:day,:open,:high,:low,:close) ON DUPLICATE KEY UPDATE '
            'open=VALUES(open),high=VALUES(high),low=VALUES(low),close=VALUES(close)'), changed)
    rows = [new[d] for d in sorted(new)]
    proof = dict(source_count=data['source_count'], row_count=len(rows), first_date=rows[0][0],
                 last_date=rows[-1][0], content_hash=digest(rows), contract_version=1)
    before = {k: str(head[k]) if k in ('first_date', 'last_date') else head[k] for k in proof} if head else None
    if before != proof:
        conn.execute(text('INSERT INTO fx_price_year(unified_code,quote_year,source_count,row_count,'
            'first_date,last_date,content_hash,contract_version,version_observed_at) VALUES(:code,:year,:source_count,'
            ':row_count,:first_date,:last_date,:content_hash,:contract_version,:observed) ON DUPLICATE KEY UPDATE '
            'source_count=VALUES(source_count),row_count=VALUES(row_count),first_date=VALUES(first_date),'
            'last_date=VALUES(last_date),content_hash=VALUES(content_hash),contract_version=VALUES(contract_version),version_observed_at=VALUES(version_observed_at)'),
            dict(code=identity(code), year=year, observed=mysql_time(envelope.observed_at), **proof))
    outcome.update(written_count=len(changed) + len(removed) + int(before != proof), confirmed=[ident])
    return outcome


def archive_state(envelope, data, outcome, previous):
    if not outcome['confirmed']:
        return previous
    versions = dict(previous.get('versions', {}))
    versions[data['identity']] = envelope.observed_at.astimezone(UTC).isoformat(timespec='microseconds')
    if len(versions) > 1800:
        raise ValueError('汇率年份状态超过十二品种150年上限')
    return dict(versions=versions, progress=confirmed_page(envelope, data, previous))
