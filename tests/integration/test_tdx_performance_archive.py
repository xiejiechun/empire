"""Five source contracts through real Redis, shared archiver and private MySQL queries."""
import asyncio
import copy
import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.performance.contract import KINDS
from tests.prefetch_source import prefetch_http
from tests.test_tdx_performance import PERIOD, directory, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to private SQL/Redis')]


@pytest.fixture(params=list(KINDS))
async def performance(request, monkeypatch):
    cfg = copy.deepcopy(load_config())
    manager = build_manager(cfg)
    kind = request.param
    c = manager.entries['collector.tdx_' + kind].plugin
    c._test_events = []
    original_envelope = c.envelope
    def capture_envelope(*args, **kw):
        value = original_envelope(*args, **kw)
        c._test_events.append(value)
        return value
    monkeypatch.setattr(c, 'envelope', capture_envelope)
    store = None
    monkeypatch.setattr('empire.features.performance.collector.quarterly_plan', lambda _: [PERIOD])
    monkeypatch.setattr('empire.features.performance.query.quarterly_plan', lambda _: [PERIOD])
    def response(*args, **kw):
        params = json.loads(kw['content'])['Params']
        body = directory(kind) if 'cache' in args[1] else source(kind, security=params[1] if kind == 'holder_count' else '')
        return httpx.Response(200, json=body)
    try:
        await manager.start(c.manifest.id)
        q = manager.registry.get(kind + '.tdx_query')
        store = manager.registry.get('redis.store')
        c.http = prefetch_http(request=AsyncMock(side_effect=response), response_policy=lambda _: None)
        yield manager, c, q, store
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            prefix = cfg['redis']['namespace'] + ':'
            keys = [k async for k in client.scan_iter(match=prefix + '*')]
            assert all(k.startswith(prefix) for k in keys)
            if keys:
                await client.delete(*keys)
            await client.aclose()


async def collect(c):
    return await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision()), 25)


@pytest.mark.parametrize('failure', ['sql', 'ack'])
async def test_failure_retains_queue_replays_and_checkpoint_loss(performance, monkeypatch, failure):
    manager, c, q, store = performance
    archive = manager.registry.get('archive.worker')
    owner, method = (q.mysql, 'archive') if failure == 'sql' else (archive, 'acknowledge')
    original = getattr(owner, method)
    attempted = asyncio.Event()
    async def interrupted(*args, **kwargs):
        attempted.set()
        raise RuntimeError('test-owned interruption')
    monkeypatch.setattr(owner, method, interrupted)
    task = asyncio.create_task(collect(c))
    try:
        await asyncio.wait_for(attempted.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await store.client.xlen(store.stream) > 0
        assert bool((await q.list_records())['rows']) == (failure == 'ack')
        requests = c.http.request.await_count
        monkeypatch.setattr(owner, method, original)
        archive.request_flush()
        await collect(c)
        assert c.http.request.await_count >= requests
        assert await store.client.xlen(store.stream) == 0
        before = (await q.list_records())['rows']
        await store.client.delete(c.ingest._checkpoint_key(c.job_key))
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        await collect(c)
        assert (await q.list_records())['rows'] == before
        assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'pass'
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_source_to_query_and_set_proof(performance):
    _, c, q, store = performance
    result = await collect(c)
    rows = (await q.list_records())['rows']
    assert len(rows) == result['collected'] == (4 if c.kind == 'earnings_quick' else 2)
    assert {r['unified_code'] for r in rows} == {'000001.SZ', '600000.SH'}
    page = await q.list_records(limit=1)
    assert page['next'] and (await q.list_records(after=page['next'], limit=1))['rows'][0]['record_key'] != page['rows'][0]['record_key']
    assert len((await q.list_records(code='000001'))['rows']) == (2 if c.kind == 'earnings_quick' else 1)
    assert await store.client.xlen(store.stream) == 0
    checks = {v.criterion: v.status for v in await q.preparation_check()}
    assert checks['coverage'] == checks['keys'] == checks['fields'] == 'pass'
    assert next(v for v in await q.preparation_check({'codes': ['600999']}) if v.criterion == 'coverage').status == 'pass'
    assert next(v for v in await q.preparation_check({'purpose': 'historical_signal'}) if v.criterion == 'temporal').status == (
        'fail' if c.kind in ('holder_count', 'earnings_disclosure') else 'pass')


async def test_source_declared_future_notice_not_historical_signal(performance):
    _, c, q, _ = performance
    if c.kind not in ('earnings_forecast', 'earnings_quick', 'earnings_report'):
        return
    async def response(*args, **kw):
        body = directory(c.kind) if 'cache' in args[1] else source(c.kind)
        if 'cache' not in args[1]:
            column = body['ResultSets'][0]['ColName'].index('T007' if c.kind == 'earnings_report' else 'T002')
            for row in body['ResultSets'][0]['Content']:
                row[column] = '2099-01-01'
        return httpx.Response(200, json=body)
    c.http.request.side_effect = response
    await collect(c)
    assert {r['announcement_date'] for r in (await q.list_records())['rows']} == {'2099-01-01'}
    checks = {v.criterion: v for v in await q.preparation_check({'purpose':'historical_signal'})}
    assert checks['coverage'].status == 'pass'
    assert checks['temporal'].status == 'fail' and checks['temporal'].blocking


async def test_hot_cold_repeat_revision_old_response_and_replay(performance):
    manager, c, q, store = performance
    await collect(c)
    archive = manager.registry.get('archive.worker')
    dml, sql_calls = [], []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if q.table in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            dml.append(statement)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    original = q.mysql.archive
    async def counted(records):
        sql_calls.append(records)
        return await original(records)
    q.mysql.archive = counted
    try:
        await collect(c)
        assert not dml and not sql_calls
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        await collect(c)
        assert not dml and sql_calls
        sql_calls.clear()
        def revised(*args, **kw):
            params = json.loads(kw['content'])['Params']
            return httpx.Response(200, json=directory(c.kind) if 'cache' in args[1] else
                source(c.kind, revised=True, security=params[1] if c.kind == 'holder_count' else ''))
        c.http.request.side_effect = revised
        await collect(c)
        assert dml and all(r['name'] == '修订名称' for r in (await q.list_records())['rows'])
        assert await store.client.xlen(store.stream) == 0
        prior = next(e for e in reversed(c._test_events) if e.raw_payload['rows'])
        rows = q.mapping.normalize(prior)['rows']
        stale = c.envelope(prior.raw_payload['unit'], [{**r, 'name': '旧响应'} for r in rows],
                           1, 'old-response', datetime.now(UTC) - timedelta(days=1))
        before = len(dml)
        await archive._archive_data(stale, q.mapping.normalize(stale))
        assert len(dml) == before
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        replay = await archive._archive_data(prior, q.mapping.normalize(prior))
        assert replay['written_count'] == 0 and len(dml) == before
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)
        q.mysql.archive = original


async def test_equal_count_different_sql_set_and_missing_proof(performance):
    _, c, q, store = performance
    await collect(c)
    # Test-owned database only; invalidate corresponding owned-source cache before SQL mutation.
    from empire.plugins.pipeline.fingerprints import FingerprintCache
    cache = FingerprintCache(store, {}, lambda _: q.mapping.FINGERPRINT_VERSION)
    await cache.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
    def alter():
        with q.mysql.engine.begin() as conn:
            conn.execute(text(f'UPDATE {q.table} SET name=\'正文不同\' LIMIT 1'))
    await q.mysql.control(alter)
    assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'fail'
    await collect(c)
    assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'pass'
    def remove_proof():
        with q.mysql.engine.begin() as conn:
            conn.execute(text('UPDATE collection_state SET payload=JSON_REMOVE(payload,\'$.units\') '
                'WHERE namespace=:namespace AND project_id=:project'), {'namespace': q.namespace, 'project': q.project_id})
    await cache.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
    await q.mysql.control(remove_proof)
    assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'fail'
    await collect(c)
    assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'pass'
