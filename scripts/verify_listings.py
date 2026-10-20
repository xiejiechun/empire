"""Random 30 plus fixed listing counterexamples through owned, guarded storage."""
import asyncio
import sys
from dataclasses import asdict

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy
from sqlalchemy import text

from empire.contracts.security import split_unified_code
from empire.core.time import CHINA
from empire.features.listings.contract import (
    CONTRACT,
    DATASET,
    JOB,
    NUMBERS,
    PROJECT,
    decode,
    digest,
    is_unusable,
    number,
    validate,
)
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

# Keep the previous verifier's market/date samples and known source limitations.
FIXED_CODES = ('000001.SZ', '000002.SZ', '000032.SZ', '600000.SH', '600519.SH',
               '300750.SZ', '688981.SH', '920009.BJ', '301139.SZ', '001381.SZ', '603107.SH')
HISTORICAL_FIXED = '301139.SZ'


def include_historical_fixed(selection, args, report):
    """An explicit historical counterexample is additional to the unchanged random pool."""
    pool = {s['unified_code']: s for s in selection['pool']}
    selected = {s['unified_code']: s for s in selection['selected']}
    # Identity/name from the documented 2026-10-06 empty-source counterexample;
    # this seeds only private request identity, never a listing business record.
    selected[HISTORICAL_FIXED] = pool.get(HISTORICAL_FIXED,
        dict(unified_code=HISTORICAL_FIXED, name='元道退'))
    selection['selected'] = sorted(selected.values(), key=lambda s: split_unified_code(s['unified_code']))
    selection['fixed'] = list(dict.fromkeys([*selection['fixed'], HISTORICAL_FIXED]))
    selection['historical_fixed'] = dict(code=HISTORICAL_FIXED, in_current_pool=HISTORICAL_FIXED in pool,
        basis='docs/ths-listings.md：2026-10-06明确暂无详情反例',
        scope='额外固定来源请求身份；不计入当前池随机30，不补造上市资料或变更生产股票池')
    report['fixed_scope_extended'] = True


def unit(row):
    security = row['unified_code']
    return security[-2:] + ':' + security[:6]


def observe_fetch(original, expected):
    async def fetch(stock, *, reservation=None, defer=False):
        def remember(result):
            row, observed, _url = result
            require(unit(row) == stock['market'] + ':' + stock['code'], '来源证券身份不同')
            require(unit(row) not in expected, '重复消费来源证券')
            require(validate(row, observed.astimezone(CHINA).date().isoformat()) == row, '来源规范内容不同')
            expected[unit(row)] = dict(row=row, observed_at=observed.isoformat())
            return result
        result = await original(stock, reservation=reservation, defer=defer)
        if not defer:
            return remember(result)
        require(isinstance(result, DeferredResponse), '来源未使用共享DeferredResponse')
        consume = result.consume
        async def recorded():
            return remember(await consume())
        result.consume = recorded
        return result
    return fetch


def observe_publish(original, expected, published):
    async def publish(envelopes, **kwargs):
        for e in envelopes:
            p, key = e.raw_payload, e.business_key
            require(e.dataset == DATASET and e.job_key == JOB and e.source == 'ths'
                    and e.schema_version == 1 and key not in published, '入队身份或重复单元无效')
            if key == 'manifest':
                require(p['row'] is None and p['manifest']['units'] == len(expected)
                        and p['manifest']['scope_hash'] == digest(list(expected)), '入队范围证明不同')
            else:
                require(key in expected and p['row'] == expected[key]['row']
                        and p['manifest'] is None and e.observed_at.isoformat() == expected[key]['observed_at'],
                        '来源与入队集合或内容不同')
        result = await original(envelopes, **kwargs)
        require(result['revision'] == kwargs['expected_revision'] + 1, '入队版本不连续')
        published.extend(e.business_key for e in envelopes)
        return result
    return publish


def read_sql(query):
    with query.mysql.read_engine.begin() as conn:
        rows = conn.execute(text('SELECT * FROM stock_listing ORDER BY unified_code')).mappings().all()
        return ({r['unified_code']: decode(r) for r in rows}, read_state(conn, query.namespace, PROJECT, 'ths'))


async def verify_scope(manager, selection, args, report):
    await manager.start('collector.ths_listings')
    c, q = manager.registry.get('collector.ths_listings'), manager.registry.get('listings.query')
    state = await c.ingest.checkpoint(JOB)
    require(state['revision'] == 0 and not state['cursor'], '私有断点非空')
    expected, published, counts = {}, [], {}
    result = report['results']['listings'] = dict(pipeline_verified=False, routes=counts, published_units=published)
    original, publish = c.fetch, c.ingest.publish_page
    c.fetch, c.ingest.publish_page = observe_fetch(original, expected), observe_publish(publish, expected, published)
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(counts)
    try:
        cursor = await c.execute(fresh=True, baseline_revision=state['revision'])
    finally:
        c.fetch, c.ingest.publish_page = original, publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
        result['source_units'] = {key: dict(digest=digest(v['row']),
            status=v['row'].get('detail_status', 'available'), listing_date=v['row'].get('listing_date'),
            history_bytes=len((v['row'].get('history') or '').encode())) for key, v in expected.items()}
    wanted = {s['unified_code'][-2:] + ':' + s['unified_code'][:6] for s in selection['selected']}
    require(set(expected) == wanted and set(published) == wanted | {'manifest'}
            and len(published) == len(wanted)+1 and cursor['phase'] == 'complete', '来源/入队/完成集合不同')
    sql_rows, sql_state = await q.mysql.read(read_sql, q)
    require(sql_rows == {v['row']['unified_code']: v['row'] for v in expected.values() if not is_unusable(v['row'])},
            'SQL规范集合或内容不同，或为缺值状态新增空业务行')
    require(sql_state['contract_version'] == CONTRACT and set(sql_state['units']) == wanted
            and sql_state['manifest']['scope_hash'] == digest(list(expected))
            and sql_state['manifest']['units'] == len(wanted), 'SQL范围证明不同')
    comparisons = {}
    for key, value in expected.items():
        row, proof = value['row'], sql_state['units'][key]
        require(proof['digest'] == digest(row) and proof['contract'] == CONTRACT
                and proof['observed_at'] == value['observed_at']
                and proof['availability'] == row.get('detail_status', 'available'), 'SQL证券证明不同')
        detail = await q.detail(row['unified_code'])
        if is_unusable(row):
            require(detail['last_valid'] is None, '私有缺值证券不应有历史业务行')
            detail = {k: v for k, v in detail.items() if k != 'last_valid'}
        require(detail == row, '正式详情与来源不同：' + key)
        page = await q.list_records(code=row['unified_code'])
        if is_unusable(row):
            require(page['rows'] == [], '缺值证券不得伪装为可用列表')
            require(page[row['detail_status'] + '_count'] == 1, '正式列表缺值状态计数不同')
        else:
            require(len(page['rows']) == 1 and page['next'] is None, '正式列表证券集合不同')
            shown = {k: number(page['rows'][0][k], k) if k in NUMBERS else page['rows'][0][k]
                     for k in row if k != 'history'}
            require(shown == {k: v for k, v in row.items() if k != 'history'}
                    and 'history' not in page['rows'][0], '正式列表字段不同或预读正文')
        comparisons[key] = dict(detail_equal=True, list_equal=True, digest=digest(row))
    planned, existing, manifest = await q.plan()
    require({s['market']+':'+s['code'] for s in planned} == wanted
            and existing == {key for key, v in expected.items() if not is_unusable(v['row'])}
            and manifest['scope_hash'] == digest(list(expected)), '正式补缺规划集合不同')
    preparation = [asdict(v) for v in await q.preparation_check({'codes': [s['unified_code'][:6] for s in selection['selected']]})]
    store, archive = manager.registry.get('redis.store'), manager.registry.get('archive.worker')
    pending = await store.client.xlen(store.stream)
    require(pending == 0 and not archive.blocked and not archive.blocked_projects and not archive.isolated,
            '本轮待归档非零或归档被隔离')
    result.update(pipeline_verified=True, strict_proxy_verified=strict_proxy(counts, len(wanted)),
                  acceptance_complete=True, random_samples_complete=True, pending=pending, cursor=cursor,
                  query_units=comparisons, preparation=preparation,
                  limitation='精确暂无/缺上市日是来源状态验收；数据准备仍失败，不代表全市场或严格历史版本完整')


def main(argv=None):
    args = verification.parser(__doc__).parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verification.verify(
        args, verify_scope, subject='listings', fixed_codes=tuple(c for c in FIXED_CODES if c != HISTORICAL_FIXED),
        minimum_random=30, require_proxy=True, prepare_scope=include_historical_fixed))
    print(('CLEANUP COMPLETE' if args.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
