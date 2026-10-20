"""Source → Redis → unified archive → indexed queries, UUID-owned SQL and Redis."""

import asyncio
import copy
import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.listing_status import dataset as mapping
from empire.features.listing_status.contract import DATASET, JOB
from tests.prefetch_source import prefetch_http
from tests.test_listing_status import envelope, row, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to isolated integration')]


@pytest.fixture
async def status():
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    manager = build_manager(cfg)
    c = manager.entries['collector.tdx_listing_status'].plugin
    store = None
    try:
        await manager.start(c.manifest.id)
        q, store = manager.registry.get('listing_status.query'), manager.registry.get('redis.store')
        c.today = lambda: date(2001, 6, 30)
        # Finite source-semantic test plan; does not claim production history complete.
        c.query.plan = AsyncMock(return_value=['2001-06'])
        def response(*a, **kw):
            import json
            day = json.loads(kw['content'])['Params'][2]
            values = [row(), row(label='恢复上市日', code='600625', market=1), row(code='832317', market=2)] if day == '2001-06-15' else []
            if day == '2001-06-16':
                values = [row(code='832317', market=2)]
            return httpx.Response(200, json=source(day, values))
        c.http = prefetch_http(request=AsyncMock(side_effect=response), response_policy=lambda _: None)
        yield manager, c, q, store
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                await client.delete(*keys)
            await client.aclose()


async def collect(c):
    return await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision()), 25)


async def test_complete_month_to_query_empty_dates_cursor_and_scope(status):
    _, c, q, store = status
    result = await collect(c)
    assert result['collected'] == 2 and c.http.request.await_count == 30
    first = await q.list_events(limit=1)
    assert first['next'] and 'description' not in first['rows'][0]
    second = await q.list_events(after=first['next'], limit=1)
    assert first['rows'][0]['record_key'] != second['rows'][0]['record_key']
    records = (await q.list_events(event_type='terminated'))['rows']
    assert len(records) == 1 and records[0]['unified_code'] == '000588.SZ'
    assert (await q.detail([records[0][k] for k in mapping.COLUMNS[:4]]))['description'] == '来源说明'
    assert await store.client.xlen(store.stream) == 0
    assert next(e for e in await q.preparation_check(dict(start='2001-06-15', end='2001-06-15')) if e.criterion == 'coverage').status == 'pass'
    assert next(e for e in await q.preparation_check() if e.criterion == 'coverage').status == 'fail'
    assert (await q.state())['coverage_through'] is None


async def test_hot_cold_duplicate_revision_stale_and_equal_count_sql_corruption(status, monkeypatch):
    manager, c, q, store = status
    await collect(c)
    archive = manager.registry.get('archive.worker')
    writes, calls = [], []
    def capture(conn, cursor, sql, params, context, executemany):
        if mapping.TABLE in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    original = q.mysql.archive
    async def counted(records):
        calls.append(1)
        return await original(records)
    monkeypatch.setattr(q.mysql, 'archive', counted)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    try:
        await collect(c)
        assert not calls and not writes
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, 'tdx')
        await collect(c)
        assert calls and not writes
        # Valid old identity missing optional text is repaired through a full snapshot.
        async with archive.lock:
            await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, 'tdx')
            with q.mysql.engine.begin() as conn:
                conn.execute(text(f'UPDATE {mapping.TABLE} SET name=\'缺失旧名\''))
        scoped = dict(start='2001-06-01', end='2001-06-30')
        assert next(e for e in await q.preparation_check(scoped) if e.criterion == 'coverage').status == 'fail'
        await collect(c)
        assert all(r['name'] == '来源简称' for r in (await q.list_events())['rows'])
        original_source = c.http.request.side_effect
        def revised(*a, **kw):
            response = original_source(*a, **kw)
            body = response.json()
            if body['ResultSets'][0]['Content']:
                body['ResultSets'][0]['Content'][0][3] = '修订说明'
            return httpx.Response(200, json=body)
        c.http.request.side_effect = revised
        await collect(c)
        records = (await q.list_events(event_type='terminated'))['rows']
        key = [records[0][k] for k in mapping.COLUMNS[:4]]
        assert (await q.detail(key))['description'] == '修订说明'
        old_writes = len(writes)
        old = envelope().model_copy(update={'observed_at': datetime.now(UTC) - timedelta(hours=1)})
        old = make_envelope(source='tdx', dataset=DATASET, job_key=JOB, batch_id=uuid4().hex, run_id='old',
            business_key='2001-06', payload=old.raw_payload).model_copy(update={'observed_at': old.observed_at})
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, 'tdx')
        state = await c.ingest.checkpoint(JOB)
        await c.ingest.publish_page([old], job_key=JOB, expected_revision=state['revision'], cursor=state['cursor'])
        await archive.flush()
        assert len(writes) == old_writes and (await q.detail(key))['description'] == '修订说明'
        async with archive.lock:
            await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, 'tdx')
            with q.mysql.engine.begin() as conn:
                conn.execute(text(f'UPDATE {mapping.TABLE} SET unified_code=\'000589.SZ\' WHERE unified_code=\'000588.SZ\''))
        assert next(e for e in await q.preparation_check(scoped) if e.criterion == 'coverage').status == 'fail'
        await collect(c)
        assert next(e for e in await q.preparation_check(scoped) if e.criterion == 'coverage').status == 'pass'
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


async def test_commit_then_ack_failure_retains_and_replays_without_download(status, monkeypatch):
    manager, c, q, store = status
    archive = manager.registry.get('archive.worker')
    acknowledge = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ack interruption')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        if (await q.list_events())['rows'] and await store.client.xlen(store.stream):
            break
        await asyncio.sleep(.05)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, RuntimeError)):
        await task
    assert await store.client.xlen(store.stream) > 0
    calls = c.http.request.await_count
    monkeypatch.setattr(archive, 'acknowledge', acknowledge)
    await archive.flush()
    await collect(c)
    assert c.http.request.await_count == calls and await store.client.xlen(store.stream) == 0


async def test_sql_failure_leaves_queue_and_month_proof_unadvanced(status, monkeypatch):
    manager, c, q, store = status
    archive = manager.registry.get('archive.worker')
    original = q.mysql.archive
    monkeypatch.setattr(q.mysql, 'archive', AsyncMock(side_effect=RuntimeError('SQL unavailable')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        if await store.client.xlen(store.stream):
            break
        await asyncio.sleep(.02)
    task.cancel()
    with pytest.raises((asyncio.CancelledError, RuntimeError)):
        await task
    assert await store.client.xlen(store.stream) and not (await q.state()).get('months')
    monkeypatch.setattr(q.mysql, 'archive', original)
    await archive.flush()
    await collect(c)
    assert await store.client.xlen(store.stream) == 0


async def test_sql_plan_missing_middle_month_and_redis_loss(status):
    _, c, q, store = status
    await collect(c)
    from empire.features.listing_status.query import ListingStatusDataPlugin
    # Formal planner after discarding only this test-owned checkpoint.
    await store.client.delete(c.ingest._checkpoint_key(JOB))
    plan = await ListingStatusDataPlugin.plan(q, date(2001, 8, 2))
    assert '2001-06' not in plan and '2001-05' in plan and '2001-07' in plan
    assert '2001-06' in await ListingStatusDataPlugin.plan(q, date(2001, 8, 2), fresh=True)
    assert (await q.state())['months']['2001-06']['contract'] == 1
