"""Owned full-unit source verification for TDX unlocks and industry summaries."""
import asyncio
import hashlib
import json
import sys

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.features.unlock_industries import source as industry_source
from empire.features.unlock_industries.contract import digest
from empire.features.unlock_industries.dataset import UnlockIndustryDataset, read_month
from empire.features.unlocks import source
from empire.features.unlocks.contract import MARKETS, monthly_plan, validate_unit
from empire.features.unlocks.dataset import UnlockDataset, read_unit
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def equal_sets(expected, *actual):
    require(all(expected == rows for rows in actual), '来源、规范化、SQL及正式查询完整集合内容不同')
    return digest(expected)


async def all_pages(query, **filters):
    rows, after, seen = [], None, set()
    while True:
        page = await query.list_records(after=after, **filters)
        rows.extend(page['rows'])
        after = page['next']
        if after is None:
            return rows
        key = tuple(after)
        require(key not in seen and len(rows) <= 100000, '分页循环或超出核验容量')
        seen.add(key)


async def verify_scope(manager, selection, args, report):
    industry = args.family == 'industries'
    ident = 'collector.tdx_unlock_industries' if industry else 'collector.tdx_unlocks'
    await manager.start(ident)
    collector = manager.entries[ident].plugin
    query = manager.registry.get('unlock_industries.tdx_query' if industry else 'unlocks.tdx_query')
    http, ingest = collector.http, collector.ingest
    original_request, original_publish = http.request, ingest.publish_page
    routes, lists, details, normalized, directory = {}, {}, {}, {}, []
    result = report['results'][collector.project_id] = dict(pipeline_verified=False, routes=routes, units={}, responses=[])

    async def observed_request(method, url, **kwargs):
        response = await original_request(method, url, **kwargs)
        try:
            require(method == 'POST', '请求方法偏离正式协议')
            params = json.loads(kwargs['content'])['Params']
            if industry:
                if url == industry_source.DIRECTORY_URL:
                    require(params == ['dxfhy', '0'] and not directory, '目录参数或重复下载')
                    directory.append(industry_source.parse_directory(response.json()))
                else:
                    require(url == industry_source.URL and len(directory) == 1, '行业协议/目录缺失')
                    month = params[0][:4] + '-' + params[0][4:] + '-01'
                    require(params == [month[:7].replace('-', ''), directory[0][1].replace('-', '')]
                            and month not in lists, '行业月份/基准/请求次数改变')
                    lists[month] = industry_source.parse_month(response.json(), month, directory[0][1])
            else:
                require(url == source.URL, '解禁来源偏离正式协议')
                if params[0] == '0':
                    month = params[1][:4] + '-' + params[1][4:6] + '-01'
                    require(month not in lists and params == source.list_params(month), '列表参数或请求次数不同')
                    lists[month] = source.parse_list(response.json(), month)
                else:
                    parents = [row for values in lists.values() for row in values if source.detail_params(row) == params]
                    require(bool(parents), '明细请求没有来源列表关联')
                    parent = parents[0]
                    require(parent['group_key'] not in details, '同一请求组重复下载')
                    details[parent['group_key']] = source.parse_detail(response.json(), parent)
            result['responses'].append(dict(params=params, bytes=len(response.content),
                sha256=hashlib.sha256(response.content).hexdigest()))
            return response
        except BaseException:
            response.close()
            raise

    async def observed_publish(envelopes, **kwargs):
        for envelope in envelopes:
            value = (UnlockIndustryDataset() if industry else UnlockDataset()).normalize(envelope)
            unit = value['unit']
            if unit == 'manifest':
                continue
            if industry:
                expected, actual = lists[unit], value['rows']
            else:
                month, market = unit.split('|')
                parents = [dict(row, detail_status='present' if details[row['group_key']] else 'source_empty',
                                detail_count=len(details[row['group_key']]))
                           for row in lists[month] if row['unified_code'].endswith(market)]
                children = sorted([row for key in {p['group_key'] for p in parents} for row in details[key]],
                                  key=lambda row: row['record_key'])
                validate_unit(unit, parents, children)
                expected, actual = [parents, children], [value['parents'], value['details']]
            equal_sets(expected, actual)
            require(unit not in normalized, '单元重复入队')
            normalized[unit] = expected
        return await original_publish(envelopes, **kwargs)

    async def check_unit(unit):
        def read():
            with query.mysql.read_engine.connect() as conn:
                return read_month(conn, unit)[1] if industry else [rows for _, rows in read_unit(conn, unit)]
        expected = normalized[unit]
        equal_sets(expected, await query.mysql.read(read))
        result['units'][unit] = dict(count=len(expected) if industry else len(expected[0]),
            digest=digest(expected), **({} if industry else dict(details=len(expected[1]))))
        if not industry:
            state = await query.state()
            require(state['units'][unit]['digest'] == digest(expected), 'SQL完整单元证明不同')
            for key in {row['group_key'] for row in expected[0]}:
                equal_sets(details[key], await query.details(key))
            for key, rows in zip(('representative_parent', 'representative_detail'), expected, strict=True):
                if rows and key not in report:
                    report[key] = rows[0]

    tokens = (USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(routes))
    http.request, ingest.publish_page = observed_request, observed_publish
    try:
        for month in [None] if industry else args.months:
            options = {} if industry else dict(start_month=month, end_month=month)
            cursor = await collector.execute(fresh=True, baseline_revision=await collector.checkpoint_revision(), **options)
            require(cursor['phase'] == 'complete', '整轮未确认完成')
            if industry:
                require(len(directory) == 1 and set(normalized) == set(lists) == set(directory[0][0]), '行业完整目录集合不同')
                units = sorted(normalized)
            else:
                units = [month + '|' + market for market in MARKETS]
                require(set(units) <= normalized.keys(), '完整三市场未发布')
            for unit in units:
                await check_unit(unit)
            if industry:
                for unit in units:
                    rows = sorted(await all_pages(query, start=unit, end=unit), key=lambda r: r['industry'])
                    equal_sets(normalized[unit], rows)
                result['directory'] = directory[0]
            else:
                end = source.list_params(month)[2]
                paged = sorted(await all_pages(query, start=month, end=end[:4]+'-'+end[4:6]+'-'+end[6:]),
                               key=lambda r: r['record_key'])
                equal_sets(sorted([row for unit in units for row in normalized[unit][0]], key=lambda r: r['record_key']), paged)
            print(json.dumps(dict(verified_unit='industry_directory' if industry else month,
                units=len(units), requests=len(result['responses']), routes=routes)), flush=True)
        if not industry:
            require(set(lists) == set(args.months), '声明月份与实际请求不同')
            require(set(details) == {p['group_key'] for rows in lists.values() for p in rows}, '必要明细请求集合缺漏')
            result['stocks'] = {}
            for stock in selection['selected']:
                code = stock['unified_code']
                expected = sorted([p for values in normalized.values() for p in values[0] if p['unified_code'] == code],
                                  key=lambda r: r['record_key'])
                equal_sets(expected, sorted(await all_pages(query, code=code), key=lambda r: r['record_key']))
                result['stocks'][code] = dict(count=len(expected), digest=digest(expected), complete=True,
                    empty_means='仅已声明完整月份无记录，不宣称范围外无解禁')
            report['scope'] = dict(months=args.months, full_market_lists=True,
                sampling='当前正式股票池随机30及固定证券，完整月份覆盖每只；有效空集保留，不换样',
                details='范围内全部来源证券的每个group只请求一次，完整正式collector与归档')
        store = manager.registry.get('redis.store')
        pending = await store.client.xlen(store.stream)
        require(pending == 0, '本轮仍有待归档消息')
        result.update(pipeline_verified=True, pending_stream=pending,
            strict_proxy_verified=strict_proxy(routes, len(result['responses'])), random_samples_complete=not industry)
        result['preparation'] = [dict(criterion=v.criterion, status=v.status, measured=v.measured, blocking=v.blocking)
                                 for v in await query.preparation_check()]
    finally:
        http.request, ingest.publish_page = original_request, original_publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])


def main(family, argv=None):
    parser = verification.parser(__doc__)
    parser.add_argument('--months', nargs='+', default=['1990-01-01', '1996-05-01', '2020-01-01',
        '2020-02-01', '2025-10-01', '2027-12-01'])
    parser.set_defaults(family=family, **({'random_count': 0} if family == 'industries' else {}))
    args = parser.parse_args(argv)
    require(len(args.months) == len(set(args.months)), '月份重复')
    for month in args.months:
        monthly_plan(month, month)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    if args.cleanup_only:
        action = verification.recover(args)
    elif family == 'industries':
        action = verification.verify(args, verify_scope, subject='unlock_industries', non_stock_scope=dict(
            unit='本轮来源目录全部月份与行业完整集合', reason='来源不按证券采集；行业不充当随机30股票', fixed=[]))
    else:
        action = verification.verify(args, verify_scope, subject='unlocks', minimum_random=30,
                                     fixed_codes=('603027.SH',), require_proxy=True)
    passed = asyncio.run(action)
    print('PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1
