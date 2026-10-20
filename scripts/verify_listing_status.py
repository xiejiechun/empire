"""Complete fixed calendar months through UUID-owned guarded storage."""
import asyncio
import copy
import sys
from dataclasses import asdict
from datetime import datetime, timedelta

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy
from sqlalchemy import text

from empire.core.time import CHINA
from empire.features.listing_status.contract import (
    COLUMNS,
    DATASET,
    JOB,
    bounds,
    content,
    digest,
    months,
    valid_proof,
)
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

FIXED_MONTHS = ('1990-12', '1999-07', '2020-05', '2021-08', '2022-04', '2024-07')


def observe_fetch(original, daily):
    async def fetch(day, **kwargs):
        def remember(value):
            require(day not in daily, '来源日期重复消费')
            daily[day] = copy.deepcopy(value)
            return value
        result = await original(day, **kwargs)
        if not isinstance(result, DeferredResponse):
            return remember(result)
        consume = result.consume
        async def recorded():
            return remember(await consume())
        result.consume = recorded
        return result
    return fetch


def observe_publish(original, daily, published, through):
    async def publish(envelopes, **kwargs):
        for e in envelopes:
            p = e.raw_payload
            a, b = bounds(p['month'], through)
            days = [(a + timedelta(days=i)).isoformat() for i in range((b-a).days+1)]
            expected = sorted([r for day in days for r in daily[day][0]], key=lambda r: tuple(r[:4]))
            require(e.dataset == DATASET and e.job_key == JOB and e.source == 'tdx'
                    and e.schema_version == 1 and e.business_key == p['month']
                    and p['month'] not in published and p['end'] == b.isoformat()
                    and p['rows'] == expected and p['source_counts'] == [daily[d][1] for d in days],
                    '来源到入队月份集合或内容不同')
        result = await original(envelopes, **kwargs)
        require(result['revision'] == kwargs['expected_revision'] + 1, '入队断点版本异常')
        published.extend(e.business_key for e in envelopes)
        return result
    return publish


async def verify_scope(manager, selection, args, report):
    through = datetime.now(CHINA).date()
    wanted = list(args.months)
    require(1 <= len(wanted) <= 6 and len(set(wanted)) == len(wanted)
            and set(wanted) <= set(months(through)), '须选择1至6个不同合法月份')
    await manager.start('collector.tdx_listing_status')
    c, q = manager.registry.get('collector.tdx_listing_status'), manager.registry.get('listing_status.query')
    state = await c.ingest.checkpoint(JOB)
    require(state['revision'] == 0 and not state['cursor'], '私有断点非空')
    daily, published, counts = {}, [], {}
    result = report['results']['listing_status'] = dict(pipeline_verified=False, routes=counts,
                                                     published_units=published, months={})
    original_plan, original_fetch, original_publish = q.plan, c.fetch, c.ingest.publish_page
    async def finite_plan(end, fresh=False):
        candidates = await original_plan(end, fresh=True)
        require(set(wanted) <= set(candidates), '私有正式计划缺失月份')
        return [m for m in candidates if m in wanted]
    q.plan, c.fetch = finite_plan, observe_fetch(original_fetch, daily)
    c.ingest.publish_page = observe_publish(original_publish, daily, published, through)
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(counts)
    try:
        cursor = await c.execute(fresh=True, baseline_revision=state['revision'])
    finally:
        q.plan, c.fetch, c.ingest.publish_page = original_plan, original_fetch, original_publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
        result['source_days'] = {day: dict(events=len(rows), count=count,
            content_digest=digest([rows, count])) for day, (rows, count) in daily.items()}
    require(cursor['phase'] == 'complete' and set(published) == set(wanted)
            and len(published) == len(wanted), '月份完成或入队集合不同')
    proofs = (await q.state()).get('months', {})
    require(set(proofs) == set(wanted), 'SQL月份证明集合不同')
    all_expected = []
    for month in wanted:
        a, b = bounds(month, through)
        days = [(a+timedelta(days=i)).isoformat() for i in range((b-a).days+1)]
        expected = sorted([r for day in days for r in daily[day][0]], key=lambda r: tuple(r[:4]))
        source_counts = [daily[d][1] for d in days]
        all_expected.extend(expected)
        actual, after, seen = [], None, set()
        while True:
            page = await q.list_events(start=a.isoformat(), end=b.isoformat(), after=after)
            for row in page['rows']:
                key = [row[k] for k in COLUMNS[:4]]
                detail = await q.detail(key)
                require(detail['found'], '正式详情缺失')
                actual.append(key + [row['name'], detail['description']])
            after = page['next']
            if after is None:
                break
            require(tuple(after) not in seen, '正式查询游标重复')
            seen.add(tuple(after))
        proof = proofs[month]
        require(actual == expected and valid_proof(proof, month, b)
                and proof['source_counts'] == source_counts
                and proof['digest'] == digest(content(expected, source_counts)), '正式查询或SQL证明与来源不同')
        preparation = [asdict(v) for v in await q.preparation_check(dict(start=a.isoformat(), end=b.isoformat()))]
        require(all(v['status'] == 'pass' for v in preparation), '有限月份准备未通过')
        result['months'][month] = dict(days=len(days), events=len(expected), digest=proof['digest'],
            types={kind: sum(r[2] == kind for r in expected) for kind in ('suspended','resumed','terminated')},
            query_equal=True, preparation=preparation)
    def read_sql():
        with q.mysql.read_engine.connect() as conn:
            return [[r[0].isoformat(), *r[1:]] for r in conn.execute(text(
                'SELECT '+','.join(COLUMNS)+' FROM security_listing_event '
                'ORDER BY event_date,unified_code,event_type,record_key LIMIT 50001')).all()]
    require(await q.mysql.read(read_sql) == sorted(all_expected, key=lambda r: tuple(r[:4])), '独立SQL集合内容不同')
    fixed = [('1999-07-12', 'terminated', None), ('2020-05-22', 'suspended', '000792.SZ'),
             ('2021-08-10', 'resumed', '000792.SZ')]
    result['fixed_regressions'] = {}
    for day, kind, security in fixed:
        if day[:7] in wanted:
            require(any(r[0] == day and r[2] == kind and (security is None or r[1] == security)
                        for r in all_expected), '既有固定历史事件缺失：'+day)
            result['fixed_regressions'][day] = dict(kind=kind, security=security, present=True)
    require(len(daily) == sum(v['days'] for v in result['months'].values())
            and all(day[:7] in wanted for day in daily), '日来源范围不完整或越界')
    store, archive = manager.registry.get('redis.store'), manager.registry.get('archive.worker')
    pending = await store.client.xlen(store.stream)
    require(pending == 0 and not archive.blocked and not archive.blocked_projects and not archive.isolated,
            '本轮待归档或隔离非空')
    result.update(pipeline_verified=True, acceptance_complete=True, strict_proxy_verified=strict_proxy(counts, len(daily)),
                  pending=pending, cursor=cursor, source_query_equal=True, full_history_complete=False,
                  limitation='完整固定月份；不按股票请求，不证明全历史、北交所或重新上市完整')


def main(argv=None):
    parser = verification.parser(__doc__)
    parser.set_defaults(random_count=0, timeout=1800)
    parser.add_argument('--months', nargs='+', default=list(FIXED_MONTHS))
    args = parser.parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    passed = asyncio.run(verification.recover(args) if args.cleanup_only else verification.verify(
        args, verify_scope, subject='listing_status', require_proxy=True,
        non_stock_scope=dict(unit='complete_calendar_months', reason='每日完整市场响应，不按股票请求或当前股票名单过滤',
                             fixed=list(args.months))))
    print(('CLEANUP COMPLETE' if args.cleanup_only else 'PASS') if passed else 'FAIL', flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
