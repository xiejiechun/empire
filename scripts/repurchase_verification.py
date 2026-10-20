"""Whole-market plan-key E2E on UUID-owned independent SQL and Redis resources."""
import asyncio
import hashlib
import json
import sys
from decimal import Decimal

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.features.repurchases import dataset
from empire.features.repurchases.contract import (
    COLUMNS,
    MAX_ROWS,
    PROJECT,
    extend_digest,
    parse,
    validate,
)
from empire.features.repurchases.query import public
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def equal_rows(expected, actual):
    expected = sorted(expected, key=lambda r: r['plan_id'])
    actual = sorted(actual, key=lambda r: r['plan_id'])
    require(expected == actual, '来源、入队与正式查询完整集合或内容不同')
    return extend_digest('0'*64, expected)


async def verify_scope(manager, selection, args, report):
    await manager.start('collector.eastmoney_repurchase')
    c = manager.registry.get('collector.eastmoney_repurchase')
    q = manager.registry.get('repurchases.query')
    original_request, original_publish = c.http.request, c.ingest.publish_page
    routes, responses, source, queued = {}, [], [], []
    result = report['results'][PROJECT] = dict(routes=routes, responses=responses,
        pipeline_verified=False, acceptance_complete=False)

    async def observed_request(method, url, **kwargs):
        response = await original_request(method, url, **kwargs)
        try:
            after = kwargs['params'].get('filter', '').split('"')[1] if 'filter' in kwargs['params'] else ''
            rows, count = parse(json.loads(response.content, parse_float=Decimal), after=after,
                                remaining=None if not responses else responses[0]['remaining']-len(source))
            source.extend(rows)
            responses.append(dict(after=after, remaining=count, rows=len(rows), bytes=len(response.content),
                sha256=hashlib.sha256(response.content).hexdigest(),
                first_id=rows[0]['plan_id'] if rows else None, last_id=rows[-1]['plan_id'] if rows else None))
            return response
        except BaseException:
            response.close()
            raise

    async def observed_publish(envelopes, **kwargs):
        staged = []
        for envelope in envelopes:
            staged.extend(dataset.normalize(envelope)['rows'])
        equal_rows(source[:len(queued)+len(staged)], queued+staged)
        value = await original_publish(envelopes, **kwargs)
        queued.extend(staged)
        return value

    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(routes)
    c.http.request, c.ingest.publish_page = observed_request, observed_publish
    try:
        cursor = await c.execute(fresh=True, baseline_revision=await c.checkpoint_revision())
        require(cursor['phase']=='complete', '回购整轮未完成归档确认')
        summary = equal_rows(source, queued)
        audit = await q.mysql.read(q.audit)
        require(audit['valid'] and audit['count']==len(source) and audit['digest']==summary==cursor['digest'],
                '正式SQL审计与来源范围证明不同')
        actual, after, seen = [], None, set()
        while True:
            page = await q.list_plans(after=after)
            for header in page['rows']:
                detail = await q.detail(header['plan_id'])
                require(detail is not None and all(detail[k]==v for k,v in header.items()), '正式列表与详情不符')
                actual.append(detail)
            after = page['next']
            if after is None:
                break
            require(tuple(after) not in seen and len(actual)<=MAX_ROWS, '正式分页循环或超出上限')
            seen.add(tuple(after))
        equal_rows(source, actual)
        def read_all():
            with q.mysql.read_engine.connect() as conn:
                return [validate({k: public(r)[k] for k in COLUMNS}) for r in
                    conn.exec_driver_sql('SELECT * FROM stock_repurchase_plan ORDER BY plan_id').mappings()]
        equal_rows(source, await q.mysql.read(read_all))
        store = manager.registry.get('redis.store')
        pending = await store.client.xlen(store.stream)
        require(pending==0, '本轮待归档消息不为0')
        result.update(pipeline_verified=True, acceptance_complete=True, pending_stream=pending,
            strict_proxy_verified=strict_proxy(routes,len(responses)), count=len(source), digest=summary,
            securities=len({r['unified_code'] for r in source}), first=source[0] if source else None,
            audit=audit, checkpoint=cursor,
            preparation=[dict(criterion=e.criterion,status=e.status,blocking=e.blocking,measured=e.measured)
                         for e in await q.preparation_check()])
        report['first'] = result['first']
    finally:
        c.http.request, c.ingest.publish_page = original_request, original_publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])


def main(argv=None):
    parser = verification.parser(__doc__)
    parser.set_defaults(random_count=0, timeout=1200)
    args = parser.parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    action = verification.recover(args) if args.cleanup_only else verification.verify(args, verify_scope,
        subject='repurchases', require_proxy=True, non_stock_scope=dict(unit='全市场方案REPURCODE完整游标',
            reason='纯组织迁移；请求按全市场方案编号而非证券过滤，完整源集合包含多市场及股份类型，不声明随机30股',fixed=[]))
    passed = asyncio.run(action)
    print('PASS' if passed else 'FAIL',flush=True)
    return 0 if passed else 1
