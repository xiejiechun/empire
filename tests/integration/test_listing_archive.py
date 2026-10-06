"""Source to formal queries, UUID-owned SQL and Redis; no production business edits."""
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
from empire.contracts.data import make_envelope
from empire.contracts.listings import DATASET, JOB, parse
from empire.core.config import load_config
from empire.plugins.datasets import listings
from tests.test_ths_listings import STOCKS, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to private database')]


@pytest.fixture
async def listing():
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    manager = build_manager(cfg)
    store = None
    try:
        await manager.start('collector.ths_listings')
        c, q = manager.registry.get('collector.ths_listings'), manager.registry.get('listings.query')
        store = manager.registry.get('redis.store')
        with q.mysql.engine.begin() as conn:
            conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:unified_code,:name)'),
                [dict(unified_code=s['code']+'.'+s['market'],name=s['name']) for s in STOCKS])
        c.session = SimpleNamespace(headers=lambda _: {'Referer':'https://basic.10jqka.com.cn/'})
        c.http = SimpleNamespace(request=AsyncMock(side_effect=lambda *a, **kw: httpx.Response(200,json=source())), response_policy=lambda _: None)
        yield manager, c, q, store
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace']+':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace']+':') for k in keys)
                await client.delete(*keys)
            await client.aclose()


async def collect(c, fresh=False):
    return await asyncio.wait_for(c.execute(fresh=fresh,baseline_revision=await c.checkpoint_revision()),20)


def unavailable_source(*args, **kwargs):
    return httpx.Response(200, json=dict(status_code=10001, data={}, status_msg='result empty'))


async def test_unavailable_archives_proof_continues_next_and_rechecks_daily(listing):
    _, c, q, store = listing
    c.http.request.side_effect = lambda *a, **kw: unavailable_source() if 'code=000001' in a[1] else httpx.Response(200, json=source())
    result = await collect(c)
    assert result['collected'] == 1 and result['unavailable'] == 1 and c.http.request.await_count == 2
    assert await q.detail('000001.SZ') == dict(unified_code='000001.SZ', detail_status='unavailable', source_status_code=10001, last_valid=None)
    assert (await q.detail('600000.SH'))['listing_date'] == '1991-04-03'
    with q.mysql.engine.connect() as conn:
        assert conn.execute(text('SELECT COUNT(*) FROM stock_listing')).scalar() == 1
    assert (await q.list_records('000001'))['unavailable_count'] == 1
    checks = await q.preparation_check({'codes': ['000001']})
    assert next(e for e in checks if e.criterion == 'fields').status != 'pass'
    assert all('来源暂无资料1' in e.measured for e in checks)
    await collect(c)
    assert c.http.request.await_count == 3  # Only unavailable rechecked in an ordinary round.
    assert await store.client.xlen(store.stream) == 0


async def test_unavailable_preserves_valid_duplicate_and_late_responses_then_recovers(listing):
    manager, c, q, store = listing
    await collect(c)
    old = await q.detail('000001.SZ')
    archive = manager.registry.get('archive.worker')
    writes = []
    def capture(conn, cursor, sql, params, context, many):
        if 'stock_listing' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    async def late(row):
        e = make_envelope(source='ths', dataset=DATASET, business_key='SZ:000001', job_key=JOB,
            run_id='late', batch_id='late', payload=dict(page=1, unit='SZ:000001', row=row, manifest=None))
        e = e.model_copy(update={'observed_at': datetime.now(UTC)-timedelta(hours=1)})
        state = await c.ingest.checkpoint(JOB)
        await archive.fingerprints.invalidate(listings.FINGERPRINT_NAMESPACE, 'ths')
        await c.ingest.publish_page([e], job_key=JOB, expected_revision=state['revision'], cursor=state['cursor'])
        await archive.flush()
    try:
        c.http.request.side_effect = unavailable_source
        await collect(c, True)
        assert (await q.detail('000001.SZ'))['last_valid'] == old and not writes
        assert all(r['detail_status'] == 'unavailable' for r in (await q.list_records())['rows'])
        await collect(c, True)  # Trusted duplicate.
        await archive.fingerprints.invalidate(listings.FINGERPRINT_NAMESPACE, 'ths')
        await collect(c, True)  # Cold duplicate.
        await late(old)
        assert (await q.detail('000001.SZ'))['detail_status'] == 'unavailable' and not writes
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=source())
        await collect(c, True)
        assert await q.detail('000001.SZ') == old and not writes
        await late(parse(dict(status_code=10001, data={}, status_msg='result empty'), STOCKS[0], '2026-10-06'))
        assert await q.detail('000001.SZ') == old and not writes
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


async def test_unavailable_sql_and_ack_failures_replay_without_redownload(listing, monkeypatch):
    manager, c, q, store = listing
    archive = manager.registry.get('archive.worker')
    original, ack = q.mysql.archive, archive.acknowledge
    c.http.request.side_effect = unavailable_source
    monkeypatch.setattr(q.mysql, 'archive', AsyncMock(side_effect=RuntimeError('sql failed')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        if (await c.ingest.checkpoint(JOB))['cursor'].get('phase') == 'awaiting_archive':
            break
        await asyncio.sleep(.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    calls = c.http.request.await_count
    assert await store.client.xlen(store.stream) > 0
    monkeypatch.setattr(q.mysql, 'archive', original)
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ack failed')))
    with pytest.raises(RuntimeError, match='ack failed'):
        await archive.flush()
    assert (await q.detail('000001.SZ'))['detail_status'] == 'unavailable'
    assert await store.client.xlen(store.stream) > 0
    monkeypatch.setattr(archive, 'acknowledge', ack)
    archive.request_flush()
    await collect(c)
    assert c.http.request.await_count == calls and await store.client.xlen(store.stream) == 0


async def test_source_date_conflict_archived_and_reported_without_changing_listing(listing):
    _, c, q, store = listing
    body = source()
    body['data'].update(listing_date='1993-10-28', establish_date='1993-12-04')
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=body)
    await collect(c)
    row = await q.detail('000001.SZ')
    assert row['listing_date'] == '1993-10-28' and row['establish_date'] == '1993-12-04'
    evidence = await q.preparation_check({'codes': ['000001']})
    assert all(e.status == 'pass' for e in evidence)
    assert any('成立日晚于上市日1条' in e.measured for e in evidence)
    assert await store.client.xlen(store.stream) == 0


async def test_source_archive_queries_daily_and_missing_proof_repair(listing):
    manager,c,q,store = listing
    result = await collect(c)
    assert result['collected'] == 2 and c.http.request.await_count == 2
    rows = (await q.list_records())['rows']
    assert {r['unified_code'] for r in rows} == {'000001.SZ','600000.SH'}
    assert all('history' not in r for r in rows)
    assert await q.detail('000001.SZ') == parse(source(),STOCKS[0],'2026-10-06')
    assert await store.client.xlen(store.stream) == 0
    first = await q.list_records(limit=1)
    assert len((await q.list_records(after=first['next'],limit=1))['rows']) == 1
    assert all(e.status == 'pass' for e in await q.preparation_check({'codes':['000001']}))
    calls = c.http.request.await_count
    await collect(c)
    assert c.http.request.await_count == calls
    archive = manager.registry.get('archive.worker')
    async with archive.lock:
        await archive.fingerprints.invalidate(listings.FINGERPRINT_NAMESPACE,'ths')
        with q.mysql.engine.begin() as conn:
            conn.execute(text("UPDATE stock_listing SET content_hash=REPEAT('0',64) WHERE unified_code='000001.SZ'"))
    assert next(e for e in await q.preparation_check() if e.criterion=='coverage').status == 'fail'
    await collect(c)
    assert c.http.request.await_count == calls+1
    assert next(e for e in await q.preparation_check({'codes':['000001','600000']}) if e.criterion=='coverage').status == 'pass'


async def test_hot_cold_no_dml_revision_stale_and_redis_loss(listing,monkeypatch):
    manager,c,q,store = listing
    await collect(c)
    archive = manager.registry.get('archive.worker')
    writes,calls = [],[]
    def capture(conn,cursor,sql,params,context,many):
        if 'stock_listing' in sql and sql.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')):
            writes.append(sql)
    event.listen(q.mysql.engine,'before_cursor_execute',capture)
    original = q.mysql.archive
    async def counted(records):
        calls.append(1)
        return await original(records)
    monkeypatch.setattr(q.mysql,'archive',counted)
    try:
        await collect(c,True)
        # Per-unit trusted hashes bypass SQL; manifest may confirm the new full-refresh time.
        assert not writes
        await archive.fingerprints.invalidate(listings.FINGERPRINT_NAMESPACE,'ths')
        await collect(c,True)
        assert calls and not writes
        changed = source()
        changed['data']['issuance_price'] = '41.0000'
        c.http.request.side_effect = lambda *a,**kw:httpx.Response(200,json=changed)
        await collect(c,True)
        assert len(writes)==2 and (await q.detail('000001.SZ'))['issuance_price']=='41'
        e = make_envelope(source='ths',dataset=DATASET,business_key='SZ:000001',job_key=JOB,
            run_id='old',batch_id='old',payload=dict(page=1,unit='SZ:000001',row=parse(source(),STOCKS[0],'2026-10-06'),manifest=None))
        e = e.model_copy(update={'observed_at':datetime.now(UTC)-timedelta(hours=1)})
        await archive.fingerprints.invalidate(listings.FINGERPRINT_NAMESPACE,'ths')
        state = await c.ingest.checkpoint(JOB)
        await c.ingest.publish_page([e],job_key=JOB,expected_revision=state['revision'],cursor=state['cursor'])
        await archive.flush()
        assert len(writes)==2 and (await q.detail('000001.SZ'))['issuance_price']=='41'
        assert await store.client.xlen(store.stream)==0
        # Simulate loss of this job's ephemeral checkpoint only; SQL proof recovers planning.
        monkeypatch.setattr(c.ingest,'checkpoint',AsyncMock(return_value={'revision':0,'cursor':{}}))
        stocks,existing,proof = await q.plan()
        assert len(stocks)==len(existing)==2 and proof['refresh_started_at']
    finally:
        event.remove(q.mysql.engine,'before_cursor_execute',capture)


async def test_commit_ack_failure_replay_and_invalid_source_no_advance(listing,monkeypatch):
    manager,c,q,store = listing
    archive = manager.registry.get('archive.worker')
    ack = archive.acknowledge
    monkeypatch.setattr(archive,'acknowledge',AsyncMock(side_effect=RuntimeError('ack failed')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        state = await c.ingest.checkpoint(JOB)
        if state['cursor'].get('phase')=='awaiting_archive' and (await q.list_records())['rows']:
            break
        await asyncio.sleep(.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await store.client.xlen(store.stream)>0
    calls = c.http.request.await_count
    monkeypatch.setattr(archive,'acknowledge',ack)
    archive.request_flush()
    await collect(c)
    assert c.http.request.await_count==calls and await store.client.xlen(store.stream)==0
    before = await c.ingest.checkpoint(JOB)
    body=source()
    del body['data']['listing_date']
    c.http.request.side_effect=lambda *a,**kw:httpx.Response(200,json=body)
    with pytest.raises(ValueError):
        await collect(c,True)
    assert await c.ingest.checkpoint(JOB)==before


async def test_same_count_different_sql_keys_missing_coverage_and_sql_failure(listing,monkeypatch):
    manager,c,q,store = listing
    await collect(c)
    archive=manager.registry.get('archive.worker')
    async with archive.lock:
        await archive.fingerprints.invalidate(listings.FINGERPRINT_NAMESPACE,'ths')
        with q.mysql.engine.begin() as conn:
            conn.execute(text("UPDATE stock_listing SET unified_code='000002.SZ' WHERE unified_code='000001.SZ'"))
    checks=await q.preparation_check()
    assert next(e for e in checks if e.criterion=='coverage').status=='fail'
    await collect(c)
    assert (await q.detail('000001.SZ'))['listing_date']=='1991-04-03'
    original=q.mysql.archive
    monkeypatch.setattr(q.mysql,'archive',AsyncMock(side_effect=RuntimeError('sql failed')))
    await archive.fingerprints.invalidate(listings.FINGERPRINT_NAMESPACE,'ths')
    task=asyncio.create_task(collect(c,True))
    for _ in range(100):
        if (await c.ingest.checkpoint(JOB))['cursor'].get('phase')=='awaiting_archive':
            break
        await asyncio.sleep(.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await store.client.xlen(store.stream)>0
    monkeypatch.setattr(q.mysql,'archive',original)
    archive.request_flush()
    await collect(c)
    assert await store.client.xlen(store.stream)==0
