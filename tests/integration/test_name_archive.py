"""Name source → canonical Redis → unified SQL archive → formal queries, isolated DB."""
import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.name_changes import SCHEMA_VERSION, pack_rows
from empire.core.config import load_config
from tests.test_name_changes import source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to isolated integration')]


@pytest.fixture(params=['company', 'security'])
async def names(request):
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    manager = build_manager(cfg)
    c = manager.entries['collector.tdx_' + request.param + '_renames'].plugin
    store = None
    try:
        await manager.start(c.manifest.id)
        q = manager.registry.get('names.' + request.param + '.query')
        store = manager.registry.get('redis.store')
        c.http = SimpleNamespace(request=AsyncMock(side_effect=lambda *a, **kw: httpx.Response(200, json=source(c.kind))), response_policy=lambda _: None)
        yield manager, c, q, store
    finally:
        await manager.shutdown()
        if store:
            # Namespace is UUID-owned; preserve every other Redis key.
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                await client.delete(*keys)
            await client.aclose()


async def collect(c):
    return await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision()), 20)


async def test_end_to_end_and_source_quality(names):
    _, c, q, store = names
    result = await collect(c)
    assert result['collected'] == 2 and c.http.request.await_count == 1
    rows = (await q.list_events())['rows']
    assert {r['unified_code'] for r in rows} == {'000001.SZ', '600000.SH'}
    assert all(r['csrc_industry'] == r['tdx_industry'] == '行业' for r in rows)
    assert (await q.list_events(limit=1))['next']
    first = await q.list_events(limit=1)
    assert len((await q.list_events(after=first['next'], limit=1))['rows']) == 1
    assert len((await q.list_events(code='000001'))['rows']) == 1
    assert await store.client.xlen(store.stream) == 0
    checks = {e.criterion: e.status for e in await q.preparation_check()}
    assert checks['coverage'] == checks['fields'] == 'pass'
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=source(c.kind, missing=True))
    await collect(c)
    assert (await q.list_events(code='000001'))['rows'][0]['old_name'] is None
    assert next(e for e in await q.preparation_check() if e.criterion == 'fields').status == 'pass'
    historical = await q.preparation_check({'purpose':'historical_signal'})
    assert next(e for e in historical if e.criterion == 'fields').status == 'fail'
    assert next(e for e in await q.preparation_check() if e.criterion == 'temporal').blocking is False


async def test_hot_cold_duplicate_revision_stale_and_same_count_wrong_sql(names, monkeypatch):
    manager, c, q, store = names
    await collect(c)
    archive = manager.registry.get('archive.worker')
    writes, calls = [], []
    def capture(conn, cursor, sql, parameters, context, executemany):
        if 'security_name_change' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    original = q.mysql.archive
    async def counted(records):
        calls.append(1)
        return await original(records)
    monkeypatch.setattr(q.mysql, 'archive', counted)
    try:
        await collect(c)
        assert not calls and not writes
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        await collect(c)
        assert calls and not writes
        # Old rows missing the added fields must be repaired through the formal source/archive path.
        async with archive.lock:
            await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
            with q.mysql.engine.begin() as conn:
                conn.execute(text('UPDATE security_name_change SET csrc_industry=NULL,tdx_industry=NULL WHERE name_kind=:kind'), {'kind':c.kind})
        assert next(e for e in await q.preparation_check() if e.criterion == 'coverage').status == 'fail'
        await collect(c)
        assert all(r['csrc_industry'] == '行业' for r in (await q.list_events())['rows'])
        changed_industry = source(c.kind)
        changed_industry['ResultSets'][0]['Content'][0][changed_industry['ResultSets'][0]['ColName'].index('tdxhy')] = '新行业'
        old_key = (await q.list_events(code='000001'))['rows'][0]['record_key']
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=changed_industry)
        await collect(c)
        revised = (await q.list_events(code='000001'))['rows'][0]
        assert revised['record_key'] == old_key and revised['tdx_industry'] == '新行业'
        changed = source(c.kind)
        changed['ResultSets'][0]['Content'][0][changed['ResultSets'][0]['ColName'].index('lastname')] = '修订名称'
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=changed)
        await collect(c)
        assert writes and (await q.list_events(code='000001'))['rows'][0]['new_name'] == '修订名称'
        old_count = len(writes)
        # Explicit old message proves SQL rejection, not just a Redis fingerprint check.
        from empire.contracts.data import make_envelope
        from empire.plugins.collectors.tdx_name_source import parse
        groups, _ = parse(c.kind, source(c.kind), '2026-10-05')
        batch = uuid4().hex
        e = make_envelope(source='tdx', dataset='names.' + c.kind + '.market', business_key='SZ',
            job_key=c.job_key, run_id=batch, batch_id=batch,
            schema_version=SCHEMA_VERSION, payload=dict(page=2, market='SZ', through='2026-10-05', **pack_rows(groups['SZ']), source_count=1))
        e = e.model_copy(update={'observed_at': datetime.now(UTC) - timedelta(hours=1)})
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        state = await c.ingest.checkpoint(c.job_key)
        await c.ingest.publish_page([e], job_key=c.job_key, expected_revision=state['revision'], cursor=state['cursor'])
        await archive.flush()
        assert len(writes) == old_count and (await q.list_events(code='000001'))['rows'][0]['new_name'] == '修订名称'
        async with archive.lock:
            await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
            with q.mysql.engine.begin() as conn:
                conn.execute(text("UPDATE security_name_change SET unified_code='000002.SZ' WHERE name_kind=:kind AND unified_code='000001.SZ'"), {'kind': c.kind})
        assert next(e for e in await q.preparation_check() if e.criterion == 'coverage').status == 'fail'
        await collect(c)
        assert next(e for e in await q.preparation_check() if e.criterion == 'coverage').status == 'pass'
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


async def test_commit_then_ack_failure_resume_without_network(names, monkeypatch):
    manager, c, q, store = names
    archive = manager.registry.get('archive.worker')
    acknowledge = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ack interruption')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        if (await q.list_events())['rows'] and await store.client.xlen(store.stream):
            break
        await asyncio.sleep(.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await store.client.xlen(store.stream) > 0
    calls = c.http.request.await_count
    monkeypatch.setattr(archive, 'acknowledge', acknowledge)
    archive.request_flush()
    await collect(c)
    assert c.http.request.await_count == calls and await store.client.xlen(store.stream) == 0


async def test_transaction_failure_retains_and_bad_source_preserves_checkpoint(names, monkeypatch):
    manager, c, q, store = names
    original = q.mysql.archive
    monkeypatch.setattr(q.mysql, 'archive', AsyncMock(side_effect=RuntimeError('SQL interruption')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        if await store.client.xlen(store.stream):
            break
        await asyncio.sleep(.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await store.client.xlen(store.stream) == 3 and not (await q.list_events())['rows']
    monkeypatch.setattr(q.mysql, 'archive', original)
    manager.registry.get('archive.worker').request_flush()
    await collect(c)
    before = await c.ingest.checkpoint(c.job_key)
    bad = source(c.kind)
    bad['ResultSets'][2]['Content'] = [[5]]
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=bad)
    with pytest.raises(ValueError):
        await collect(c)
    assert await c.ingest.checkpoint(c.job_key) == before
    assert len((await q.list_events())['rows']) == 2
