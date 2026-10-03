"""Lossless source → Redis → shared archive → SQL query in UUID-owned scope."""
import asyncio
import copy
import os
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.plugins.datasets.intraday import FINGERPRINT_NAMESPACE, JOB, identity
from tests.test_kaipanla_intraday import STOCK, listing, row
from tests.test_kaipanla_source import sample

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


@pytest.fixture
async def intraday_db():
    cfg = copy.deepcopy(load_config())
    token = uuid4().hex
    cfg['redis']['namespace'] = 'empire:test:' + token
    manager = build_manager(cfg)
    query = manager.entries['data.intraday'].plugin
    collector = manager.entries['collector.kaipanla_intraday'].plugin
    query.source = collector.source = 'kaipanla'
    store = mysql = None
    try:
        await manager.start('collector.kaipanla_intraday')
        mysql, store = query.mysql, manager.registry.get('redis.store')
        query.plan = AsyncMock(return_value=([STOCK], [date(2021, 1, 4), date(2021, 1, 5)]))
        query.suspended_days = AsyncMock(return_value=set())
        async def request(method, url, **options):
            if 'eastmoney.com' in url:
                return httpx.Response(200, json=listing())
            data = options['attempt_options']()['data']
            kind = 'trend' if data['a'] == 'GetStockTrend' else 'auction'
            body = sample(kind)
            body['day'] = data['Day'].replace('-', '')
            return httpx.Response(200, json=body)
        collector.http = SimpleNamespace(request=AsyncMock(side_effect=request), response_policy=lambda _: None)
        async def publish(value=None, observed=None):
            value = copy.deepcopy(value or row())
            batch = uuid4().hex
            envelope = make_envelope(source=query.source, dataset='intraday.day', business_key=identity(value),
                job_key=JOB, batch_id=batch, run_id=batch, payload=dict(page=1, rows=[value]))
            if observed:
                envelope = envelope.model_copy(update={'observed_at': observed})
            state = await collector.ingest.checkpoint(JOB)
            await collector.ingest.publish_page([envelope], job_key=JOB, expected_revision=state['revision'],
                                                cursor={'test': batch})
            await manager.registry.get('archive.worker').flush()
            return envelope
        yield manager, query, collector, publish
    finally:
        await manager.stop('pipeline.archive', cascade=True)
        if mysql:
            def cleanup():
                with mysql.engine.begin() as conn:
                    conn.execute(text('DELETE FROM stock_intraday'), {'source': query.source})
                    conn.execute(text('DELETE FROM collection_state WHERE namespace=:namespace'),
                                 {'namespace': cfg['redis']['namespace']})
            await mysql.control(cleanup)
        if store:
            keys = [k async for k in store.client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith('empire:test:' + token + ':') for k in keys)
                await store.client.delete(*keys)
        await manager.shutdown()


async def test_two_source_days_to_lossless_formal_query_and_no_per_page_wait(intraday_db):
    manager, query, collector, _ = intraday_db
    archive = manager.registry.get('archive.worker')
    async with archive.lock:
        task = asyncio.create_task(collector.execute())
        for _ in range(100):
            if collector.stats['status'] == 'awaiting_archive':
                break
            await asyncio.sleep(.02)
        assert collector.http.request.await_count == 5
        assert await manager.registry.get('redis.store').client.xlen(archive.redis.stream) == 2
        assert not task.done()
    await asyncio.wait_for(task, 10)
    for day in ('2021-01-04', '2021-01-05'):
        result = await query.day('SZ', '000001', day)
        assert result['data']['auction'] == sample('auction')['bid']
        assert [r[0] for r in result['data']['trend']] == [r[0] for r in sample('trend')['trend']]
    assert all(c.status == 'pass' for c in await query.preparation_check({'codes': ['000001']}))
    assert all(c.status == 'pass' for c in await query.preparation_check(
        {'codes': ['000001'], 'start': '2021-01-04', 'end': '2021-01-04'}))
    assert await archive.redis.client.xlen(archive.redis.stream) == 0


async def test_hot_cold_no_dml_revision_and_late_old_response(intraday_db, monkeypatch):
    manager, query, _, publish = intraday_db
    archive, mysql = manager.registry.get('archive.worker'), query.mysql
    start = datetime.now(UTC) - timedelta(minutes=10)
    await publish(observed=start)
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'stock_intraday' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(mysql.engine, 'before_cursor_execute', capture)
    try:
        original = mysql.archive
        calls = []
        async def counted(records):
            calls.append(1)
            return await original(records)
        monkeypatch.setattr(mysql, 'archive', counted)
        await publish(observed=start + timedelta(minutes=1))
        assert not calls and not writes
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        await publish(observed=start + timedelta(minutes=2))
        assert calls and not writes
        changed = row()
        changed['auction'][0][1] = 11
        await publish(changed, start + timedelta(minutes=4))
        assert (await query.day('SZ', '000001', '2021-01-04'))['data']['auction'][0][1] == 11
        count = len(writes)
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        await publish(observed=start + timedelta(minutes=3))
        assert len(writes) == count
        assert (await query.day('SZ', '000001', '2021-01-04'))['data']['auction'][0][1] == 11
        assert await archive.redis.client.xlen(archive.redis.stream) == 0
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', capture)


async def test_commit_ack_replay_and_sql_failure_retain_message(intraday_db, monkeypatch):
    manager, query, _, publish = intraday_db
    archive, store = manager.registry.get('archive.worker'), manager.registry.get('redis.store')
    original = query.mysql.archive
    monkeypatch.setattr(query.mysql, 'archive', AsyncMock(side_effect=RuntimeError('SQL test failure')))
    with pytest.raises(RuntimeError, match='SQL test failure'):
        await publish()
    assert await store.client.xlen(store.stream) == 1
    assert await query.day('SZ', '000001', '2021-01-04') is None
    monkeypatch.setattr(query.mysql, 'archive', original)
    acknowledge = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ack test failure')))
    with pytest.raises(RuntimeError, match='ack test failure'):
        await archive.flush()
    assert await query.day('SZ', '000001', '2021-01-04')
    assert await store.client.xlen(store.stream) == 1
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'stock_intraday' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(query.mysql.engine, 'before_cursor_execute', capture)
    try:
        monkeypatch.setattr(archive, 'acknowledge', acknowledge)
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        await archive.flush()
        assert not writes and await store.client.xlen(store.stream) == 0
    finally:
        event.remove(query.mysql.engine, 'before_cursor_execute', capture)


async def test_old_missing_lifecycle_and_same_count_wrong_set_are_repaired(intraday_db):
    manager, query, _, publish = intraday_db
    await publish()
    archive = manager.registry.get('archive.worker')
    async with archive.lock:
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        with query.mysql.engine.begin() as conn:
            conn.execute(text("UPDATE stock_intraday SET payload=JSON_REMOVE(payload,'$.lifecycle')"),
                         {'source': query.source})
    assert not await query.covered_days('SZ', '000001', date(2021, 1, 4), date(2021, 1, 5), lifecycle=None)
    with pytest.raises(ValueError):
        await query.day('SZ', '000001', '2021-01-04')
    await publish()
    assert await query.day('SZ', '000001', '2021-01-04')
    async with archive.lock:
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        with query.mysql.engine.begin() as conn:
            conn.execute(text("UPDATE stock_intraday SET payload=JSON_SET(payload,'$.trend[1][0]','09:30')"),
                         {'source': query.source})
    checks = await query.preparation_check({'codes': ['000001']})
    assert next(c for c in checks if c.criterion == 'fields').status == 'fail'
    await publish()
    assert await query.day('SZ', '000001', '2021-01-04')


async def test_lost_checkpoint_uses_sql_content_and_restores_missing_day(intraday_db):
    manager, query, collector, _ = intraday_db
    await collector.execute()
    store = manager.registry.get('redis.store')
    async with manager.registry.get('archive.worker').lock:
        await manager.registry.get('archive.worker').fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        with query.mysql.engine.begin() as conn:
            conn.execute(text("DELETE FROM stock_intraday WHERE trade_date='2021-01-04'"),
                         {'source': query.source})
    await store.client.delete(collector.ingest._checkpoint_key(JOB))
    await collector.execute()
    assert await query.day('SZ', '000001', '2021-01-04')
    assert await store.client.xlen(store.stream) == 0


async def test_source_middle_gap_does_not_block_later_archive_or_fake_complete(intraday_db):
    manager, query, collector, _ = intraday_db
    query.plan.return_value = ([STOCK], [date(2021, 1, 4), date(2021, 1, 5), date(2021, 1, 6)])
    original = collector.http.request.side_effect
    async def request(method, url, **options):
        if 'attempt_options' in options:
            data = options['attempt_options']()['data']
            if data['Day'] == '2021-01-05' and data['a'] == 'GetStockBid':
                return httpx.Response(200, json={'errcode': '1017'})
        return await original(method, url, **options)
    collector.http.request.side_effect = request
    with pytest.raises(ValueError, match='仍有来源缺口'):
        await asyncio.wait_for(collector.execute(), 10)
    assert await query.day('SZ', '000001', '2021-01-04')
    assert await query.day('SZ', '000001', '2021-01-05') is None
    assert await query.day('SZ', '000001', '2021-01-06')
    cursor = (await collector.ingest.checkpoint(JOB))['cursor']
    assert cursor['index'] == 1 and cursor['phase'] == 'collecting'
    assert cursor['first_gap']['trade_date'] == '2021-01-05'
    assert await manager.registry.get('redis.store').client.xlen(manager.registry.get('redis.store').stream) == 0
    assert next(c for c in await query.preparation_check({'codes': ['000001']})
                if c.criterion == 'coverage').status == 'fail'
