"""Read-only production configuration, reviewed sources and private full-pipeline proof."""
import asyncio
import hashlib
import sys

import source_verification as verification
from PySide6.QtCore import QCoreApplication
from source_verification import require, strict_proxy

from empire.features.trading_rules import sources
from empire.features.trading_rules.contract import KINDS, digest, project
from empire.features.trading_rules.dataset import canonical_payload
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def source_payload(kind, decoded):
    if kind == 'stamp_duty':
        return sources.stamp_parameters(*(decoded[u] for u in (sources.TAX_LAW, sources.TAX_RATE, sources.TAX_HALF)))
    if kind == 'transfer_fee':
        return sources.transfer_parameters(decoded[sources.FEE_ANNOUNCEMENT]).result()
    return sources.exchange_parameters(kind, *(decoded[u] for u in (sources.SH_FILE, sources.SZ_FILE, sources.BJ_FILE)))


def equal_payload(expected, rows, citations):
    require(expected['rows'] == rows and expected['citations'] == citations,
            '规则参数或引用完整集合/内容不同；相同行数不能证明完整')
    return digest([rows, citations])


async def query_all(q, market=''):
    values, after, seen = [], None, set()
    while True:
        page = await q.list_rules(market=market, after=after, limit=3)
        values.extend(page['rows'])
        after = page['next']
        if after is None:
            break
        require(after not in seen and len(values) <= 1000, '规则正式分页循环或超限')
        seen.add(after)
    citations = []
    for key in sorted({r['citation_key'] for r in values}):
        value = await q.citation(key)
        require(value is not None and value['citation_key'] == key, '规则缺少正式引用详情')
        citations.append(value)
    return values, citations


async def verify_scope(manager, selection, args, report):
    await manager.start('collector.rules_' + next(iter(KINDS)))
    provider = manager.registry.get('rules.source')
    http = provider.http
    original_request = http.request
    decoded, responses, routes, queued = {}, [], {}, {}
    report['responses'], report['routes'] = responses, routes
    ingest = manager.registry.get('ingest.publish')
    original_publish = ingest.publish_page

    async def observed_request(method, url, **kwargs):
        response = await original_request(method, url, **kwargs)
        try:
            decoded[url] = sources.decode_source(url, response.content)
            responses.append(dict(url=url, method=method, bytes=len(response.content),
                                  sha256=hashlib.sha256(response.content).hexdigest()))
            return response
        except BaseException:
            response.close()
            raise

    async def observed_publish(envelopes, **kwargs):
        staged = {}
        for envelope in envelopes:
            kind = envelope.business_key
            require(kind in KINDS and envelope.job_key == project(kind) + '-v1', '规则发布归属错误')
            expected = canonical_payload(kind, source_payload(kind, decoded))
            actual = canonical_payload(kind, envelope.raw_payload)
            equal_payload(expected, actual['rows'], actual['citations'])
            require(kind not in queued and kind not in staged, '规则完整批重复发布')
            staged[kind] = actual
        result = await original_publish(envelopes, **kwargs)
        queued.update(staged)
        return result

    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not args.proxy_only), ROUTE_COUNTS.set(routes)
    http.request, ingest.publish_page = observed_request, observed_publish
    try:
        # Five exchange outputs reuse the formal parsed cache. Observing and
        # decoding bytes adds no extra source request or durable response copy.
        for kind in KINDS:
            capability = 'collector.rules_' + kind
            await manager.start(capability)
            c = manager.registry.get(capability)
            q = manager.registry.get('rules.' + kind + '.query')
            entry = report['results'][project(kind)] = dict(pipeline_verified=False, acceptance_complete=False)
            cursor = await c.execute(fresh=True, baseline_revision=await c.checkpoint_revision())
            require(cursor['phase'] == 'complete' and c.last_source is not None, '规则整轮未完成或来源证明缺失')
            expected = canonical_payload(kind, source_payload(kind, decoded))
            equal_payload(expected, queued[kind]['rows'], queued[kind]['citations'])
            sql_rows, sql_refs, state = await q.mysql.read(q.snapshot)
            summary = equal_payload(expected, sql_rows, sql_refs)
            values, citations = await query_all(q)
            equal_payload(expected, values, citations)
            for market in ('SH', 'SZ', 'BJ', 'CN'):
                filtered, refs = await query_all(q, market)
                rows = [r for r in expected['rows'] if r['market'] == market]
                keys = {r['citation_key'] for r in rows}
                equal_payload(dict(rows=rows, citations=[r for r in expected['citations'] if r['citation_key'] in keys]), filtered, refs)
            require(await q.citation('0' * 64) is None, '未知引用不应返回其他项目条款')
            require(state['digest'] == summary and state['row_count'] == len(values), '规则同事务状态与查询内容不同')
            store = manager.registry.get('redis.store')
            pending = await store.client.xlen(store.stream)
            require(pending == 0, '本轮待归档不为0')
            entry.update(pipeline_verified=True, acceptance_complete=True, pending_stream=pending,
                         rows=len(values), citations=len(citations), digest=summary, state=state,
                         markets=sorted({r['market'] for r in values}), source_queue_sql_query_equal=True,
                         preparation=[dict(criterion=e.criterion, status=e.status, blocking=e.blocking, measured=e.measured)
                                      for e in await q.preparation_check()])
        require(set(queued) == set(KINDS), '七项规则发布集合不完整')
        all_proxy = strict_proxy(routes, len(responses))
        for entry in report['results'].values():
            entry['strict_proxy_verified'] = all_proxy
        report['source_scope'] = '当前已审核沪深北规则、印花税及2022过户费转述公告；用途缺口保持'
    finally:
        http.request, ingest.publish_page = original_request, original_publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])


def main(argv=None):
    parser = verification.parser(__doc__)
    parser.set_defaults(random_count=0, timeout=1200)
    args = parser.parse_args(argv)
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv[:1])
    action = verification.recover(args) if args.cleanup_only else verification.verify(args, verify_scope,
        subject='trading_rules', require_proxy=True, non_stock_scope=dict(unit='七项已审核官方文档完整参数与引用集合',
            reason='纯组织迁移；来源按法规/税费文档组采集，无按股票请求入口，逐kind核验全部键和内容，不声明随机30股', fixed=[]))
    passed = asyncio.run(action)
    print('PASS' if passed else 'FAIL', flush=True)
    return 0 if passed else 1
