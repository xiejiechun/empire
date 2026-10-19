"""Finite real index years through private Redis, unified archive and public queries."""
import asyncio
import sys
from dataclasses import asdict
from decimal import Decimal

import source_verification as verification
from catalogue_verification import (
    observe_fetch,
    observe_publish,
    public_pages,
    require_drained,
    verify_catalogue,
)
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy
from sqlalchemy import text

from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.security import index_code
from empire.features.index_prices.dataset import sql_rows
from empire.features.indices.contract import digest
from empire.plugins.infra.collection_state import read_state
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

FIXED_CODES = ('399411', '1A0001', '399001', '1B0300', '399317')
KNOWN_NEGATIVE = ('399317', '2014-12-05')


def canonical(rows):
    return [[row['trade_date'].isoformat()] + [None if row[key] is None else
        format(Decimal(row[key]).normalize(), 'f') for key in ('open', 'high', 'low', 'close', 'volume', 'amount')]
        for row in rows]


def verify_known_negative(code, rows):
    if code == KNOWN_NEGATIVE[0]:
        found = [row for row in rows if row['trade_date'].isoformat() == KNOWN_NEGATIVE[1]]
        require(len(found) == 1 and found[0]['amount'] is not None and found[0]['amount'] < 0
                and found[0]['volume_amount_valid'] is False, '固定负成交额来源反例缺失或被改写')


async def verify_scope(manager, selection, args, report):
    codes = selection['non_stock_scope']['fixed']
    # Populate this private database using the real, complete formal catalogue path.
    await verify_catalogue(manager, 'indices', args.proxy_only, report)
    await manager.start('collector.ths_index_prices')
    collector = manager.registry.get('collector.ths_index_prices')
    query = manager.registry.get('index.prices.query')
    collector.selected_codes = codes
    state = await collector.ingest.checkpoint(collector.job_key)
    require(state['revision'] == 0 and not state['cursor'], '行情私有断点非空')
    sources, counts, published = {}, {}, []
    result = report['results']['index_prices'] = dict(pipeline_verified=False, routes=counts,
        source_units={}, published_units=published, fixed_codes=codes, known_negative=KNOWN_NEGATIVE)

    def remember(call, value):
        code, unit = call[0], call[1] if len(call) > 1 else 'last'
        identity = code + ':' + str(unit)
        require(identity not in sources, '行情来源单元重复')
        sources[identity] = value
        result['source_units'][identity] = dict(digest=digest(value),
            count=len(value['rows']) if unit == 'last' and value else len(value) if value else 0,
            available=value is not None)

    def check(envelope):
        payload, identity = envelope.raw_payload, envelope.business_key
        code = payload['code']
        if envelope.dataset == 'index.price.status':
            snapshot = sources[code + ':last']
            expected = {key: snapshot[key] for key in ('start', 'end', 'years', 'total')} if snapshot else {}
            require(payload['available'] == (snapshot is not None) and payload['snapshot'] == expected,
                    '行情状态入队与来源不同')
        else:
            require(envelope.dataset == 'index.price.year' and payload['mode'] == 'full'
                    and payload['rows'] == sources[identity], '行情年度来源与入队内容不同')

    original, publish = collector.fetch, collector.ingest.publish_page
    collector.fetch = observe_fetch(original, remember)
    collector.ingest.publish_page = observe_publish(publish, check, published)
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(counts)
    try:
        cursor = await collector.execute(fresh=True, baseline_revision=state['revision'])
    finally:
        collector.fetch, collector.ingest.publish_page = original, publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
    require(cursor.get('phase') == 'complete', '行情未完成')
    expected_units = {code + ':last' for code in codes}
    for code in codes:
        snapshot = sources[code + ':last']
        if snapshot:
            expected_units.update(code + ':' + year for year in snapshot['years'])
    require(set(sources) == expected_units, '行情来源年度集合不同')
    published_units = {row['identity'] for row in published}
    require(len(published) == len(expected_units) and published_units ==
            {unit.replace(':last', ':status') for unit in expected_units}, '行情入队年度集合不同')

    def compare_sql():
        with query.mysql.read_engine.begin() as conn:
            state = read_state(conn, query.namespace, collector.project_id, 'ths')
            summaries = {}
            for code in codes:
                snapshot = sources[code + ':last']
                status = state.get('indices', {}).get(code, {})
                expected = {k: snapshot[k] for k in ('start', 'end', 'years', 'total')} if snapshot else {}
                require(status.get('available') == (snapshot is not None) and status.get('snapshot') == expected,
                        '行情SQL状态与来源不同')
                heads = conn.execute(text('SELECT * FROM index_price_year WHERE index_code=:code ORDER BY quote_year'),
                                     dict(code=code)).mappings().all()
                require({str(h['quote_year']) for h in heads} == set(expected.get('years', {})), 'SQL年度集合不同')
                for head in heads:
                    year = head['quote_year']
                    rows = sql_rows(conn, code, year)
                    expected_rows = sources[code + ':' + str(year)]
                    require(rows == expected_rows and head['content_hash'] == digest(rows)
                            and head['row_count'] == len(rows) and head['complete'], 'SQL行情集合/内容/证明不同')
                summaries[code] = dict(years=len(heads), rows=sum(h['row_count'] for h in heads))
            return summaries

    result['sql_comparison'] = await query.mysql.read(compare_sql)
    queries = {}
    for code in codes:
        snapshot = sources[code + ':last']
        all_rows = []
        if snapshot:
            for year in sorted(snapshot['years']):
                expected = sources[code + ':' + year]
                options = dict(code=code, start=year+'-01-01', end=year+'-12-31')
                rows = await public_pages(query.browse, **options, limit=500)
                chart = await query.chart_series(**options)
                require(canonical(rows) == expected == canonical(chart['rows']), '正式行情列表/图表集合或内容不同')
                all_rows.extend(rows)
        verify_known_negative(code, all_rows)
        queries[code] = dict(count=len(all_rows), digest=digest(canonical(all_rows)), query_equal=True)
    scope = PreparationScope.parse(dict(index_codes=codes))
    audit = await query.mysql.read(lambda: query.audit(scope))
    require(audit[0] and not audit[3], '行情正式audit覆盖不完整')
    preparation = [asdict(e) for e in await query.preparation_check(dict(index_codes=codes))]
    result.update(pipeline_verified=True, strict_proxy_verified=strict_proxy(counts, len(sources)),
                  acceptance_complete=True, pending=await require_drained(manager), cursor=cursor,
                  public_query=queries, preparation=preparation, audit=dict(complete=audit[0], rows=audit[1],
                    problems=audit[3], unavailable=audit[2], quality_counts=list(audit[5:])),
                  limitations='仅固定指数当前可得全部年度；负成交额/缺OHLC等原值和用途失败保留，不宣称全目录历史完整或30股准入')


def parser():
    value = verification.parser(__doc__)
    value.set_defaults(random_count=0, timeout=7200)
    value.add_argument('--index-codes', nargs='*', default=[], help='在固定反例之外增加有限指数')
    return value


def main(argv=None):
    args = parser().parse_args(argv)
    codes = list(dict.fromkeys((*FIXED_CODES, *args.index_codes)))
    require(len(codes) <= 10, '有限指数验证最多10项，不可删除固定反例')
    for code in codes:
        index_code(code)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else
        verification.verify(args, verify_scope, subject='index_prices', require_proxy=True,
            non_stock_scope=dict(unit='index_all_available_years', reason='按固定指数全部来源年份采集，不按股票采集', fixed=codes)))
    print(('CLEANUP COMPLETE' if args.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
