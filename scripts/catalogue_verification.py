"""Observe complete catalogue sources through the unchanged shared pipeline."""
from __future__ import annotations

import copy
from dataclasses import asdict

from source_verification import require, strict_proxy

from empire.features.industries.contract import market
from empire.features.yuanhang_indices.contract import digest
from empire.plugins.collection.unit_prefetch import DeferredResponse
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


def observe_fetch(original, remember):
    """Observe parsed content only when its ordered consumer resolves it."""
    async def fetch(*args, **kwargs):
        value = await original(*args, **kwargs)
        if not isinstance(value, DeferredResponse):
            remember(args, copy.deepcopy(value))
            return value
        consume = value.consume

        async def observed():
            result = await consume()
            remember(args, copy.deepcopy(result))
            return result

        value.consume = observed
        return value
    return fetch


def observe_publish(original, check, published):
    async def publish(envelopes, **kwargs):
        proofs = []
        for envelope in envelopes:
            check(envelope)
            proofs.append(dict(dataset=envelope.dataset, identity=envelope.business_key,
                               digest=digest(envelope.raw_payload)))
        result = await original(envelopes, **kwargs)
        require(result['revision'] == kwargs['expected_revision'] + 1, '入队断点版本异常')
        published.extend(proofs)
        return result
    return publish


async def require_drained(manager):
    store, worker = manager.registry.get('redis.store'), manager.registry.get('archive.worker')
    pending = await store.client.xlen(store.stream)
    require(pending == 0 and not worker.blocked and not worker.blocked_projects and not worker.isolated,
            '本轮待归档非零或归档隔离')
    return pending


async def public_pages(read, **kwargs):
    rows, after, seen = [], None, set()
    while True:
        page = await read(**kwargs, **({'after': after} if after is not None else {}))
        rows.extend(page['rows'])
        after = page.get('next')
        if after is None:
            return rows
        token = repr(after)
        require(token not in seen and len(rows) <= 1000000, '正式查询游标重复或越界')
        seen.add(token)


async def verify_catalogue(manager, kind, proxy_only, report):
    require(kind == 'industries', '目录类型无效')
    await manager.start('collector.ths_' + kind)
    collector = manager.registry.get('collector.ths_' + kind)
    query = manager.registry.get(kind + '.query')
    state = await collector.ingest.checkpoint(collector.job_key)
    require(state['revision'] == 0 and not state['cursor'], '目录私有断点非空')
    sources, counts, published = {}, {}, []
    result = report['results'][kind] = dict(pipeline_verified=False, routes=counts,
                                          published_units=published, source_units={})

    def remember(args, value):
        parser = args[1]
        identity = (getattr(parser, 'keywords', {}) or {}).get('code' if kind == 'indices' else 'industry', 'catalog')
        require(identity not in sources, '来源完整单元重复')
        sources[identity] = value
        result['source_units'][identity] = dict(digest=digest(value), count=len(value) if isinstance(value, list)
                                               else len(value['members']))

    def expected_industries():
        return [dict(row, members=sources[row['code']]) for row in sources['catalog']]

    def check(envelope):
        payload = envelope.raw_payload
        require(envelope.dataset == 'industry.snapshot' and envelope.business_key == 'current'
                and payload['industries'] == expected_industries(), '行业来源与正式入队集合不同')

    original, publish = collector.fetch, collector.ingest.publish_page
    collector.fetch = observe_fetch(original, remember)
    collector.ingest.publish_page = observe_publish(publish, check, published)
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(not proxy_only), ROUTE_COUNTS.set(counts)
    try:
        cursor = await collector.execute(fresh=True, baseline_revision=state['revision'])
    finally:
        collector.fetch, collector.ingest.publish_page = original, publish
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
    require(cursor.get('phase') == 'complete', '目录未完成')
    require(set(sources) == {'catalog'} | {row['code'] for row in sources['catalog']}, '目录与成员来源集合不同')
    expected = expected_industries()
    actual, state = await query.mysql.read(query.snapshot)
    require(actual == expected and state.get('digest') == digest(expected), '行业SQL集合/内容/证明不同')
    require(len(published) == 1, '行业应只发布一份完整snapshot')
    directory = await public_pages(query.directory, limit=200)
    require(directory == [dict(industry_code=row['code'], name=row['name'], member_count=len(row['members']))
                          for row in expected], '行业正式目录查询不同')
    rows, offset = [], 0
    while True:
        page = await query.list_members(offset=offset, limit=500)
        rows.extend(page['rows'])
        if len(rows) >= page['total']:
            break
        require(bool(page['rows']) and len(rows) <= 15000, '行业正式分页停滞或越界')
        offset += len(page['rows'])
    members = [dict(industry_code=row['code'], industry_name=row['name'], market=market(code), code=code, name=name)
               for row in expected for code, name in row['members']]
    require(rows == members, '行业正式成员查询集合或内容不同')
    result.update(catalogue_count=len(expected), member_count=len(members))
    result.update(pipeline_verified=True, strict_proxy_verified=strict_proxy(counts, len(sources)),
                  acceptance_complete=True, cursor=cursor, pending=await require_drained(manager),
                  public_query_equal=True, preparation=[asdict(e) for e in await query.preparation_check()],
                  limitations='仅当前完整目录和实际返回成员；非股票采集粒度，不证明历史调样或30股准入')
