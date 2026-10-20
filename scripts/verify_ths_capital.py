"""Nine capital sections through owned storage and the unchanged formal pipeline."""
import asyncio
import sys
from dataclasses import asdict

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.contracts.preparation_scope import PreparationScope
from empire.core.time import CHINA
from empire.features.ths_capital.contract import (
    DATASET,
    JOB,
    PROJECT,
    SECTIONS,
    TABLE_SECTIONS,
    TABLES,
    digest,
    fields,
    number,
    validate,
)
from empire.features.ths_capital.dataset import read_window
from empire.features.ths_capital.transport import SCHEMA, unpack
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

# Previous fixed failures: missing percentages/releases/targets and currencies.
FIXED_CODES = ('000014.SZ', '000039.SZ', '000060.SZ', '000061.SZ', '000156.SZ',
               '000415.SZ', '000513.SZ', '601969.SH')


def summarize(value):
    return dict(digest=digest(value), count=sum(map(len, value['rows'].values())),
                tables={table: dict(count=len(rows), digest=digest(rows))
                        for table, rows in value['rows'].items()}, availability=value['availability'])


def observe_fetch(original, expected):
    async def fetch(stock, *, reservation=None, defer=False):
        def remember(result):
            value, observed, url = result
            key = stock['unified_code']
            require(key not in expected, '来源证券重复消费')
            validate(key, value['rows'], value['availability'], today=observed.astimezone(CHINA).date())
            expected[key] = dict(value=value, observed_at=observed.isoformat(timespec='microseconds'))
            return result
        result = await original(stock, reservation=reservation, defer=defer)
        if not defer:
            return remember(result)
        require(isinstance(result, DeferredResponse), '正式来源没有返回DeferredResponse')
        consume = result.consume
        async def observed_consume():
            return remember(await consume())
        result.consume = observed_consume
        return result
    return fetch


def expected_manifest(expected):
    securities, count, rolling = sorted(expected), 0, digest([])
    for security in securities:
        value = expected[security]['value']
        size = sum(map(len, value['rows'].values()))
        count += size
        rolling = digest([rolling, security, digest(value), size])
    return dict(units=len(securities), count=count, scope_hash=digest(securities),
                digest=rolling, securities=securities)


def observe_publish(original, expected, published):
    async def publish(envelopes, **kwargs):
        for envelope in envelopes:
            key, payload = envelope.business_key, envelope.raw_payload
            require(envelope.dataset == DATASET and envelope.job_key == JOB
                    and envelope.source == 'ths' and envelope.schema_version == SCHEMA
                    and key not in published, '入队身份或重复单元无效')
            rows = unpack(payload['rows'])
            if key == 'manifest':
                require(payload['manifest'] == expected_manifest(expected)
                        and rows == {t: [] for t in TABLES} and not payload['availability'], '入队完整范围证明不同')
            else:
                require(key in expected and dict(rows=rows, availability=payload['availability'])
                        == expected[key]['value'], '来源与正式入队集合或内容不同')
        result = await original(envelopes, **kwargs)
        require(result['revision'] == kwargs['expected_revision'] + 1, '入队版本不连续')
        published.extend(e.business_key for e in envelopes)
        return result
    return publish


def canonical_projection(table, row):
    return {key: number(row[key]) if kind == 'num' and row[key] is not None else row[key]
            for key, (_, kind) in fields(table).items() if kind != 'text'}


async def compare_queries(query, security, value):
    """Every public page, detail and parent/child link, not only SQL row counts."""
    result = {}
    for table in TABLES:
        wanted = {r['record_key']: r for r in value['rows'][table]}
        actual = {}
        for section in TABLE_SECTIONS[table]:
            after, seen = None, set()
            for _ in range(10001):
                page = await query.browse(table, section, code=security, after=after, limit=100)
                for row in page['rows']:
                    key = row['record_key']
                    require(key not in actual and bool(row['in_window']), '正式列表业务键重复或窗口无效')
                    actual[key] = canonical_projection(table, row)
                after = page['next']
                if after is None:
                    break
                token = repr(after)
                require(token not in seen, '正式游标重复')
                seen.add(token)
            else:
                raise ValueError('正式查询未有界结束')
        require(actual == {k: canonical_projection(table, row) for k, row in wanted.items()},
                '正式列表集合或字段不同：' + security + '/' + table)
        for key, expected in wanted.items():
            detail = await query.detail(table, key)
            require(detail is not None and bool(detail['in_window'])
                    and {k: detail[k] for k in fields(table)} == expected, '正式详情内容不同：' + key)
            if table == 'capital_encumbrance':
                children = sorted((r for r in value['rows']['capital_release'] if r['parent_key'] == key),
                                  key=lambda r: r['record_key'])
                returned = sorted(({k: r[k] for k in fields('capital_release')} for r in detail['releases']),
                                  key=lambda r: r['record_key'])
                require(returned == children, '正式详情解除关联不同')
        result[table] = dict(rows=len(wanted), digest=digest(sorted(wanted.values(), key=lambda r: r['record_key'])),
                             public_list_equal=True, public_details_equal=True)
    return result


async def verify_scope(manager, selection, args, report):
    await manager.start('collector.ths_capital')
    collector, query = manager.registry.get('collector.ths_capital'), manager.registry.get('ths_capital.query')
    state = await collector.ingest.checkpoint(JOB)
    require(state['revision'] == 0 and not state['cursor'], '私有验证断点非空')
    expected, published, counts = {}, [], {}
    result = report['results']['ths_capital'] = dict(pipeline_verified=False, routes=counts,
                                                   published_units=published, source_units={})
    original, publish = collector.fetch, collector.ingest.publish_page
    collector.fetch = observe_fetch(original, expected)
    collector.ingest.publish_page = observe_publish(publish, expected, published)
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(counts)
    try:
        cursor = await collector.execute(fresh=True, baseline_revision=state['revision'])
    finally:
        collector.fetch, collector.ingest.publish_page = original, publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
        result['source_units'] = {key: summarize(row['value']) for key, row in expected.items()}
    wanted = {s['unified_code'] for s in selection['selected']}
    require(set(expected) == wanted and set(published) == wanted | {'manifest'}
            and len(published) == len(wanted) + 1 and cursor['phase'] == 'complete', '来源/入队/完成证券集合不同')
    sql_state = await query.mysql.read(lambda: read_sql_state(query))
    manifest = expected_manifest(expected)
    require(sql_state.get('contract_version') == 1 and set(sql_state['units']) == wanted
            and {k: sql_state['manifest'][k] for k in manifest} == manifest, 'SQL范围证明不同')
    comparisons = {}
    for security, row in expected.items():
        value, proof = row['value'], sql_state['units'][security]
        require(proof['observed_at'] == row['observed_at'] and proof['digest'] == digest(value['rows'])
                and proof['count'] == sum(map(len, value['rows'].values()))
                and proof['availability'] == value['availability'], 'SQL证券完整证明不同')
        def read(security=security):
            with query.mysql.read_engine.begin() as conn:
                return read_window(conn, security)
        require(await query.mysql.read(read) == value['rows'], '当前SQL窗口集合或内容不同：' + security)
        comparisons[security] = await compare_queries(query, security, value)
    audit = await query.mysql.read(query.audit, PreparationScope())
    require(audit['complete'] and set(audit['stamps']) == wanted
            and audit['count'] == manifest['count'], '正式审计范围或内容不完整')
    preparation = {section: [asdict(check) for check in await query.preparation_check(section)] for section in SECTIONS}
    store, archive = manager.registry.get('redis.store'), manager.registry.get('archive.worker')
    pending = await store.client.xlen(store.stream)
    require(pending == 0 and not archive.blocked and not archive.blocked_projects and not archive.isolated,
            '本轮待归档非零或归档被隔离')
    require(collector.project_id == PROJECT and collector.job_key == JOB and collector.stats['status'] == 'complete',
            '采集身份或完成状态不同')
    result.update(pipeline_verified=True, strict_proxy_verified=strict_proxy(counts, len(wanted)),
                  acceptance_complete=True, random_samples_complete=True, pending=pending, cursor=cursor,
                  query_units=comparisons, sql_manifest=sql_state['manifest'], preparation=preparation,
                  audit={**audit, 'stamps': {k: stamp.isoformat() for k, stamp in audit['stamps'].items()}})


def read_sql_state(query):
    with query.mysql.read_engine.begin() as conn:
        return read_state(conn, query.namespace, PROJECT, 'ths')


def main(argv=None):
    options = verification.parser(__doc__).parse_args(argv)
    _qt_app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(options) if options.cleanup_only else verification.verify(
        options, verify_scope, subject='ths-capital', fixed_codes=FIXED_CODES, minimum_random=30, require_proxy=True))
    print(('CLEANUP COMPLETE' if options.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
