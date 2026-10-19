"""Observe complete catalogue sources through the unchanged shared pipeline."""
from __future__ import annotations

import copy
from dataclasses import asdict

from source_verification import require, strict_proxy

from empire.features.indices.contract import digest, member_identity
from empire.features.industries.contract import market
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
    require(kind in ('indices', 'industries'), '目录类型无效')
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
        if kind == 'indices':
            identity = envelope.business_key
            expected = (payload.get('catalog') if identity == 'catalog' else
                        {key: payload[key] for key in ('available', 'members')})
            require(expected == sources[identity], '指数来源与正式入队内容不同')
        else:
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
    if kind == 'indices':
        heads, complete, _, unavailable, unknown, count, problems, proofs = await query.mysql.read(query.snapshot_audit)
        require(complete and not problems and set(proofs) == set(sources), '指数正式集合证明不完整')
        expected_catalog = sources['catalog']
        require([dict(code=r['index_code'], name=r['name'], group=r['source_group']) for r in heads] == expected_catalog,
                '指数目录SQL内容不同')
        require(len(published) == len(sources) and {p['identity'] for p in published} == set(sources), '指数入队集合不完整')
        for code, value in sources.items():
            expected = value if code == 'catalog' else [value['available'], value['members']]
            require(proofs[code]['hash'] == digest(expected), '指数SQL证明与来源不同')
        rows = await public_pages(query.browse, mode='indices', limit=500)
        require([dict(code=r['index_code'], name=r['index_name'], group=r['source_group']) for r in rows] == expected_catalog,
                '指数正式目录查询内容不同')
        members = await public_pages(query.browse, mode='members', limit=500)
        expected = [dict(index_code=row['code'], source_code=code, unified_code=member_identity(code), name=name)
                    for row in expected_catalog for code, name in sources[row['code']]['members']]
        require([{key: row[key] for key in ('index_code', 'source_code', 'unified_code', 'name')} for row in members] == expected,
                '指数正式成员查询集合或内容不同')
        result.update(member_count=count, catalogue_count=len(heads), unavailable=unavailable, unknown_identity_count=unknown)
    else:
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
