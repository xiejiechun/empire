"""Source → Redis → unified archive → indexed SQL query, UUID-owned database."""
import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.repurchases.contract import DATASET, JOB, URL
from tests.prefetch_source import prefetch_http
from tests.test_repurchases import feed, source_row

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to isolated SQL and Redis')]


@pytest.fixture
async def plans():
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    m, store = build_manager(cfg), None
    source = [source_row()]
    try:
        await m.start('collector.eastmoney_repurchase')
        c, q, store = m.registry.get('collector.eastmoney_repurchase'), m.registry.get('repurchases.query'), m.registry.get('redis.store')
        async def request(*args, **kwargs):
            p = kwargs['params']
            after = p.get('filter', '').split('"')[1] if 'filter' in p else ''
            values = sorted([r for r in source if r['REPURCODE'] > after], key=lambda r: r['REPURCODE'])
            return httpx.Response(200, request=httpx.Request('GET', URL), json=feed(values[:500], len(values)))
        c.http = prefetch_http(request=AsyncMock(side_effect=request))
        yield m, c, q, store, source
    finally:
        await m.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                await client.delete(*keys)
            await client.aclose()


async def collect(c):
    return await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision()), 20)


async def test_hot_cold_revision_stale_and_missing_field_repair(plans, monkeypatch):
    m, c, q, store, source = plans
    await collect(c)
    assert (await q.detail('1'))['actual_quantity'] == '100'
    assert (await q.list_plans(code='600000', progress='004'))['rows']
    assert (await q.preparation_check())[2].status == 'pass'
    archive = m.registry.get('archive.worker')
    writes, calls = [], []
    def capture(conn, cursor, sql, parameters, context, executemany):
        if 'stock_repurchase_plan' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    original = q.mysql.archive
    async def counted(records):
        calls.append(1)
        return await original(records)
    monkeypatch.setattr(q.mysql, 'archive', counted)
    try:
        await collect(c)
        assert not calls and not writes and await store.client.xlen(store.stream) == 0
        await archive.fingerprints.invalidate('eastmoney_repurchase_v1', 'eastmoney')
        await collect(c)
        assert calls and not writes
        source[0]['REMARK2'] = '本轮累计说明'
        old_payload = None
        # Observe real formal messages, without storing successful raw source bodies.
        publish = c.ingest.publish_page
        async def capture_publish(envelopes, **kw):
            nonlocal old_payload
            old_payload = envelopes[0].raw_payload
            return await publish(envelopes, **kw)
        monkeypatch.setattr(c.ingest, 'publish_page', capture_publish)
        await collect(c)
        assert writes and (await q.detail('1'))['progress_remark'] == '本轮累计说明'
        async with archive.lock:
            await archive.fingerprints.invalidate('eastmoney_repurchase_v1', 'eastmoney')
            with q.mysql.engine.begin() as conn:
                conn.execute(text('UPDATE stock_repurchase_plan SET progress_remark=NULL'))
        assert (await q.preparation_check())[2].status == 'fail'
        await collect(c)
        assert (await q.detail('1'))['progress_remark'] == '本轮累计说明'
        before = len(writes)
        stale = copy.deepcopy(old_payload)
        stale['rows'][0]['progress_remark'] = '迟到旧说明'
        batch = uuid4().hex
        e = make_envelope(source='eastmoney', dataset=DATASET, job_key=JOB, business_key=batch+':1',
            run_id=batch, batch_id=batch, payload=stale).model_copy(update={'observed_at': datetime.now(UTC)-timedelta(hours=1)})
        state = await c.ingest.checkpoint(JOB)
        await archive.fingerprints.invalidate('eastmoney_repurchase_v1', 'eastmoney')
        await c.ingest.publish_page([e], job_key=JOB, expected_revision=state['revision'], cursor=state['cursor'])
        await archive.flush()
        assert len(writes) == before and (await q.detail('1'))['progress_remark'] == '本轮累计说明'
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


async def test_delayed_archive_does_not_block_next_page_and_pagination(plans, monkeypatch):
    m, c, q, store, source = plans
    source[:] = [source_row(str(i)) for i in range(1, 602)]
    gate = asyncio.Event()
    original = q.mysql.archive
    async def delayed(records):
        await gate.wait()
        return await original(records)
    monkeypatch.setattr(q.mysql, 'archive', delayed)
    task = asyncio.create_task(collect(c))
    try:
        for _ in range(200):
            if (await c.ingest.checkpoint(JOB))['cursor'].get('collected') == 601:
                break
            await asyncio.sleep(.02)
        assert (await c.ingest.checkpoint(JOB))['cursor']['collected'] == 601
        assert c.http.request.await_count == 2 and await store.client.xlen(store.stream) >= 2
        gate.set()
        await task
        first = await q.list_plans(limit=200)
        second = await q.list_plans(after=first['next'], limit=200)
        assert len(first['rows']) == len(second['rows']) == 200
        assert not {r['plan_id'] for r in first['rows']} & {r['plan_id'] for r in second['rows']}
        assert (await q.mysql.read(q.audit))['valid']
        assert await store.client.xlen(store.stream) == 0
    finally:
        gate.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_commit_then_ack_failure_and_redis_checkpoint_loss(plans, monkeypatch):
    m, c, q, store, source = plans
    archive = m.registry.get('archive.worker')
    acknowledge = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('test ack interruption')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        if (await q.detail('1')) and await store.client.xlen(store.stream):
            break
        await asyncio.sleep(.03)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    calls = c.http.request.await_count
    monkeypatch.setattr(archive, 'acknowledge', acknowledge)
    archive.request_flush()
    await collect(c)
    assert c.http.request.await_count == calls and await store.client.xlen(store.stream) == 0
    # Simulate only this test-owned checkpoint/cache loss, never a shared Redis restart.
    await store.client.delete(c.ingest._checkpoint_key(JOB))
    await archive.fingerprints.invalidate('eastmoney_repurchase_v1', 'eastmoney')
    await collect(c)
    assert c.http.request.await_count == calls+1 and (await q.mysql.read(q.audit))['valid']


async def test_failed_sql_retains_queue_and_same_count_different_collection(plans, monkeypatch):
    m, c, q, store, source = plans
    await collect(c)
    archive = m.registry.get('archive.worker')
    async with archive.lock:
        await archive.fingerprints.invalidate('eastmoney_repurchase_v1', 'eastmoney')
        with q.mysql.engine.begin() as conn:
            conn.execute(text("UPDATE stock_repurchase_plan SET plan_id='2' WHERE plan_id='1'"))
    assert (await q.preparation_check())[2].status == 'fail'
    original = q.mysql.archive
    monkeypatch.setattr(q.mysql, 'archive', AsyncMock(side_effect=RuntimeError('test SQL interruption')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        if await store.client.xlen(store.stream):
            break
        await asyncio.sleep(.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await store.client.xlen(store.stream) > 0
    monkeypatch.setattr(q.mysql, 'archive', original)
    archive.request_flush()
    await collect(c)
    assert (await q.detail('1')) and await store.client.xlen(store.stream) == 0
    # Historical extra rows are retained; source disappearance must remain a visible coverage mismatch.
    assert (await q.preparation_check())[2].status == 'fail'
