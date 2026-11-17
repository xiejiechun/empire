import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.graymarket.codec import pack
from empire.features.graymarket.contract import DATASET, JOB
from empire.features.graymarket.dataset import GraymarketDataset
from tests.prefetch_source import prefetch_http
from tests.test_graymarket import DayAssembly, parsed, response

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Private SQL/Redis opt-in")]


@pytest.fixture
async def pipeline():
    cfg = load_config()
    manager, store = build_manager(cfg), None
    try:
        await manager.start("collector.eastmoney_graymarket")
        c, q = manager.registry.get("collector.eastmoney_graymarket"), manager.registry.get("graymarket.query")
        store = manager.registry.get("redis.store")
        with q.mysql.engine.begin() as conn:
            conn.execute(text("INSERT INTO trade_calendar(trade_date,is_trade,updated_at) VALUES ('2026-11-02',1,NOW())"))
        def fetch(*args, **kw):
            return httpx.Response(200, content=json.dumps(response(total=101, page=kw['params']['StartPage']), default=str).encode())
        c.http = prefetch_http(request=AsyncMock(side_effect=fetch))
        yield manager, c, q, store
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg["redis"])
            keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                await client.delete(*keys)
            await client.aclose()


async def collect(c):
    return await asyncio.wait_for(c.execute(start="2026-11-02", end="2026-11-02",
        baseline_revision=await c.checkpoint_revision()), 30)


async def test_maintenance_plan_is_bounded_and_rejects_calendar_holes(pipeline):
    from datetime import date

    manager, c, q, store = pipeline
    first, last = date(2026, 5, 11), date(2026, 11, 2)
    days = [(first+timedelta(days=i)).isoformat() for i in range((last-first).days)]
    with q.mysql.engine.begin() as conn:
        conn.execute(text('INSERT INTO trade_calendar(trade_date,is_trade,updated_at) VALUES (:d,1,NOW())'),
                     [dict(d=d) for d in days])
    assert await q.maintenance_plan('2026-11-02', recent=3) == ['2026-10-31','2026-11-01','2026-11-02']
    assert await q.maintenance_plan('2026-11-02') == days[:5]
    with q.mysql.engine.begin() as conn:
        conn.execute(text("DELETE FROM trade_calendar WHERE trade_date='2026-05-12'"))
    with pytest.raises(ValueError, match='日历存在缺日'):
        await q.maintenance_plan('2026-11-02', recent=1)


async def test_pipeline_hot_cold_stale_and_revision(pipeline):
    manager, c, q, store = pipeline
    await collect(c)
    assembly = DayAssembly(parsed(response()))
    assembly.add(parsed(response(page=2), 2))
    expected = assembly.finish()
    assert await q.history("2026-11-02") == expected
    assert await store.client.xlen(store.stream) == 0
    page = await q.browse(limit=1)
    other = await q.browse(after=page['next'], limit=1)
    assert page['rows'][0]['unified_code'] != other['rows'][0]['unified_code']
    dml = []
    def track(conn, cursor, sql, parameters, context, executemany):
        if sql.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) and 'graymarket_' in sql:
            dml.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', track)
    event.listen(q.mysql.archive_engine, 'before_cursor_execute', track)
    archive, mapping = manager.registry.get('archive.worker'), GraymarketDataset()
    try:
        await collect(c)
        assert not dml
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, 'eastmoney')
        await collect(c)
        assert not dml
        revised = [list(r) for r in expected]
        revised[0][3] = str(int(revised[0][3]) + 1)
        revised[0][4] = str(int(revised[0][4]) + 1)
        e = make_envelope(source='eastmoney', dataset=DATASET, job_key=JOB, business_key='2026-11-02',
            batch_id='revision', run_id='revision', payload=dict(page=1,date='2026-11-02',rows=pack(revised),source_latest='2026-11-02'))
        await archive._archive_data(e, mapping.normalize(e))
        assert await q.history('2026-11-02') == revised
        corrected = [list(row) for row in revised]
        corrected[0][0] = '920992.BJ'
        corrected.sort(key=lambda row: row[0])
        repair = e.model_copy(update={'observed_at': datetime.now(UTC),
            'raw_payload': {**e.raw_payload, 'rows': pack(corrected)}})
        await archive._archive_data(repair, mapping.normalize(repair))
        assert await q.history('2026-11-02') == corrected
        assert (await q.browse(code='920992.BJ'))['rows'][0]['unified_code'] == '920992.BJ'
        assert (await q.browse(code='920'))['rows'][0]['unified_code'] == '920992.BJ'
        assert (await q.browse(code='920992.bj'))['rows'][0]['unified_code'] == '920992.BJ'
        assert (await q.browse(code='999'))['rows'] == []
        stale=e.model_copy(update={'observed_at':datetime.now(UTC)-timedelta(hours=1),
            'raw_payload':{**e.raw_payload,'rows':pack(expected)}})
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE,'eastmoney')
        assert (await archive._archive_data(stale,mapping.normalize(stale)))['written_count']==0
        assert await q.history('2026-11-02') == corrected
    finally:
        event.remove(q.mysql.engine,'before_cursor_execute',track)
        event.remove(q.mysql.archive_engine,'before_cursor_execute',track)


async def test_transaction_failure_commit_replay_and_preparation(pipeline, monkeypatch):
    manager,c,q,store=pipeline
    archive=manager.registry.get('archive.worker')
    await archive.stop()
    archive.stop_event.clear()
    task=asyncio.create_task(collect(c))
    async with asyncio.timeout(5):
        while await store.client.xlen(store.stream)!=1:
            await asyncio.sleep(.02)
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)
    mapping=next(x.mapping for x in manager.registry.get('dataset.catalog').contributions if DATASET in x.mapping.DATASETS)
    original=mapping.write
    def fail(*args):
        original(*args)
        raise RuntimeError('transaction failure')
    monkeypatch.setattr(mapping,'write',fail)
    with pytest.raises(RuntimeError,match='transaction failure'):
        await archive.flush()
    assert await q.history('2026-11-02') == [] and await store.client.xlen(store.stream)==1
    monkeypatch.setattr(mapping,'write',original)
    put=archive.fingerprints.put
    monkeypatch.setattr(archive.fingerprints,'put',AsyncMock(side_effect=RuntimeError('post commit')))
    with pytest.raises(RuntimeError,match='post commit'):
        await archive.flush()
    assert len(await q.history('2026-11-02'))==101 and await store.client.xlen(store.stream)==1
    monkeypatch.setattr(archive.fingerprints,'put',put)
    await archive.flush()
    assert await store.client.xlen(store.stream)==0
    await collect(c)
    scope=dict(start='2026-11-02',end='2026-11-02',purpose='analysis')
    assert all(e.status=='pass' or not e.blocking for e in await q.preparation_check(scope))
    with q.mysql.engine.begin() as conn:
        conn.execute(text("UPDATE graymarket_daily SET unified_code='999999.SZ' WHERE unified_code='000001.SZ'"))
    assert next(e for e in await q.preparation_check(scope) if e.criterion=='keys').status=='fail'
