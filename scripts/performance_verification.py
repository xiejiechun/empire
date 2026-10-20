"""Finite complete-unit E2E; explicitly not a full-history completion certificate."""
import asyncio
import hashlib
import json
import sys
from datetime import datetime
from unittest.mock import patch

import source_verification as verification
from performance_storage import PerformanceStorage
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.core.time import CHINA
from empire.features.performance import collector as runtime
from empire.features.performance.contract import UNIT_KINDS, digest, identity, project
from empire.features.performance.dataset import PerformanceDataset, decode, read_unit
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def equal_rows(kind, expected, actual):
    fields = set(expected[0]) if expected else None
    require(not actual or fields is not None, '正式查询出现来源不存在记录')
    actual = [{k: r[k] for k in fields} for r in actual] if fields else []
    def ordered(rows):
        return sorted(rows, key=lambda row: identity(kind, row))
    require(ordered(expected) == ordered(actual), '来源与规范化/SQL/正式查询完整集合或内容不同')
    return digest(ordered(expected))


async def all_pages(query, **filters):
    rows, after, seen = [], None, set()
    while True:
        result = await query.list_records(after=after, **filters)
        rows.extend(result['rows'])
        after = result['next']
        if after is None:
            return rows
        key = tuple(after)
        require(key not in seen and len(rows) <= 100000, '正式分页循环或超出有界范围')
        seen.add(key)


async def verify_kind(manager, kind, selection, args, result):
    await manager.start('collector.tdx_' + kind)
    c = manager.entries['collector.tdx_' + kind].plugin
    q = manager.registry.get(kind + '.tdx_query')
    http, ingest = c.http, c.ingest
    original_request, original_fetch, original_publish = http.request, c.fetch, ingest.publish_page
    original_plan = runtime.quarterly_plan
    routes, sources, normalized, responses, failures, directories = {}, {}, {}, [], [], []
    selected = {s['unified_code'] for s in selection['selected']}
    result.update(kind=kind, routes=routes, units={}, responses=responses, failures=failures,
                  pipeline_verified=False, acceptance_complete=False,
                  limitation='有限完整单元，测试进程限定计划，不证明1980/1990至今或生产覆盖')

    async def observed_request(method, url, **kwargs):
        response = await original_request(method, url, **kwargs)
        record = dict(params=json.loads(kwargs['content'])['Params'],
            bytes=len(response.content), sha256=hashlib.sha256(response.content).hexdigest())
        try:
            sets = response.json()['ResultSets']
            record['shape'] = [dict(declared=s.get('Count'), actual=len(s.get('Content', []))) for s in sets]
            if len(sets) == 3:
                record['source_total'] = sets[2]['Content']
            if kind == 'earnings_disclosure' and 'T007' in sets[0]['ColName']:
                columns = sets[0]['ColName']
                rows = [dict(zip(columns, r, strict=True)) for r in sets[0]['Content']]
                today = datetime.now(CHINA).date().isoformat()
                bad = [r for r in rows if isinstance(r.get('T007'), str) and r['T007'] > today]
                record['future_actual_count'] = len(bad)
                record['future_actual_examples'] = [{k: r[k] for k in ('code', 'sc', 'T002', 'T007')} for r in bad[:5]]
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            record['shape_unavailable'] = True
        responses.append(record)
        return response

    async def observed_fetch(unit=None, *, directory=False, reservation=None, defer=False):
        if directory and directories:
            return directories[0]
        value = await original_fetch(unit, directory=directory, reservation=reservation, defer=defer)
        if directory:
            directories.append(value)
            return value
        def remember(parsed):
            rows, total = parsed
            sources[unit or 'latest'] = rows
            if kind == 'holder_count' and unit is None:
                subset = [r for r in rows if r['unified_code'] in selected]
                require({r['unified_code'] for r in subset} == selected, '冻结证券不全在最新目录，不能换样')
                return subset, len(subset)
            return rows, total
        if defer:
            consume = value.consume
            async def observed_consume():
                return remember(await consume())
            value.consume = observed_consume
            return value
        return remember(value)

    async def observed_publish(envelopes, **kwargs):
        for envelope in envelopes:
            value = PerformanceDataset(kind).normalize(envelope)
            unit, rows = value['unit'], value['rows']
            if unit == 'manifest':
                continue
            if kind == 'holder_count':
                expected = list(sources[unit])
                current = next(r for r in sources['latest'] if r['unified_code'] == unit)
                matches = [r for r in expected if identity(kind, r) == identity(kind, current)]
                require(not matches or matches == [current], '最新与历史同键内容冲突')
                if not matches:
                    expected.append(current)
            else:
                period, market = unit.split('|')
                expected = [r for r in sources[period] if r['unified_code'].endswith(market)]
            equal_rows(kind, expected, rows)
            normalized[unit] = rows
        return await original_publish(envelopes, **kwargs)

    tokens = (USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(routes))
    http.request, c.fetch, ingest.publish_page = observed_request, observed_fetch, observed_publish
    try:
        if kind == 'holder_count':
            scopes = [None]
        elif kind == 'shareholder_changes':
            scopes = args.months
        else:
            directory = await c.fetch(directory=True)
            scopes = list(dict.fromkeys([*args.periods, directory[0]]))
        result['requested_scopes'] = scopes
        for scope in scopes:
            if kind not in ('holder_count', 'shareholder_changes'):
                runtime.quarterly_plan = lambda latest: [scope]
            try:
                options = dict(start_month=scope, end_month=scope) if kind == 'shareholder_changes' else {}
                cursor = await c.execute(fresh=True, baseline_revision=await c.checkpoint_revision(), **options)
                require(cursor['phase'] == 'complete', '完整测试单元未完成正式确认')
            except (ValueError, KeyError, TypeError) as exc:
                failures.append(dict(scope=scope, type=type(exc).__name__, message=str(exc)))
            print(json.dumps(dict(kind=kind, scope=scope, units=len(normalized), failures=len(failures), routes=routes)), flush=True)
        store = manager.registry.get('redis.store')
        async with asyncio.timeout(120):
            while await store.client.xlen(store.stream):
                await asyncio.sleep(.1)
        state = await q.state()
        for unit, expected in normalized.items():
            def read():
                with q.mysql.read_engine.connect() as conn:
                    return [decode(kind, r) for r in read_unit(conn, kind, unit)]
            equal_rows(kind, expected, await q.mysql.read(read))
            proof = state['units'][unit]
            require(proof['digest'] == digest(expected) and proof['count'] == len(expected), 'SQL单元证明不同')
            result['units'][unit] = dict(count=len(expected), digest=digest(expected))
        result['stocks'] = {}
        for code in sorted(selected):
            expected = [r for rows in normalized.values() for r in rows if r['unified_code'] == code]
            content_digest = equal_rows(kind, expected, await all_pages(q, code=code))
            result['stocks'][code] = dict(count=len(expected), digest=content_digest,
                complete=not failures, empty_means='仅声明完整单元无记录，范围外未知')
        result.update(pipeline_verified=bool(normalized), acceptance_complete=not failures,
            random_samples_complete=not failures, pending_stream=0,
            strict_proxy_verified=strict_proxy(routes, len(responses)))
        result['preparation'] = [dict(criterion=v.criterion, status=v.status, measured=v.measured, blocking=v.blocking)
                                for v in await q.preparation_check()]
    finally:
        http.request, c.fetch, ingest.publish_page = original_request, original_fetch, original_publish
        runtime.quarterly_plan = original_plan
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])


async def verify_scope(manager, selection, args, report):
    report['scope'] = dict(periods=args.periods, months=args.months,
        latest_period_included=True, holder_count='随机及固定证券全部可得历史；最新完整目录只限定测试计划',
        known_failures='披露实际日期超前、报告2022-03-31总数反例保留，未清生产错误')
    for kind in args.kinds:
        result = report['results'][project(kind)] = {}
        await verify_kind(manager, kind, selection, args, result)


def main(default_kinds=None, argv=None):
    parser = verification.parser(__doc__)
    parser.add_argument('--kinds', nargs='+', choices=tuple(UNIT_KINDS), default=default_kinds or list(UNIT_KINDS))
    parser.add_argument('--periods', nargs='+', default=['2013-12-31', '2022-03-31', '2026-06-30', '2026-09-30'])
    parser.add_argument('--months', nargs='+', default=['1990-01-01', '2010-01-01', '2014-06-01', '2026-09-01'])
    args = parser.parse_args(argv)
    require(len(args.kinds) == len(set(args.kinds)), 'kind重复')
    require(len(args.periods) == len(set(args.periods)) and len(args.months) == len(set(args.months)), '声明单元重复')
    require('earnings_report' not in args.kinds or '2022-03-31' in args.periods,
            '业绩报告必须保留已知失败2022-03-31固定单元')
    for value in args.periods + args.months:
        runtime.day(value)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    action = verification.recover(args) if args.cleanup_only else verification.verify(
        args, verify_scope, subject='tdx_performance', fixed_codes=('601919.SH', '601958.SH', '601139.SH'),
        minimum_random=30, require_proxy=True)
    # This command owns its single process and one run. Restore the shared
    # factory even on cancellation; resource lifecycle/recovery remains shared.
    with patch.object(verification, 'PrivateStorage', PerformanceStorage):
        passed = asyncio.run(action)
    print('PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1
