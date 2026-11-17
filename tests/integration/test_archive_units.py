"""Batch rollback, exact replay and zero-SQL proofs on the formal archive path."""
import asyncio
import os
from dataclasses import replace
from uuid import uuid4

import pytest
from sqlalchemy import event
from test_news_archive import news_db as news_db

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit integration opt-in required')]


async def manual_worker(manager):
    worker = manager.registry.get('archive.worker')
    worker.task.cancel()
    await asyncio.gather(worker.task, return_exceptions=True)
    worker.task = None
    worker.limits = replace(worker.limits, work_time_ms=5000)
    return worker


async def test_batch_member_failure_rolls_back_all_then_replay_and_hot_confirmation(news_db, monkeypatch):
    manager, publish, query = news_db
    worker = await manual_worker(manager)
    store, mysql = manager.registry.get('redis.store'), manager.registry.get('mysql.store')
    batch = uuid4().hex
    for page in range(1, 4):
        await publish(100 + page, page=page, batch=batch, flush=False)
    original = worker.catalog.write

    def fail_third(connection, envelope, data):
        result = original(connection, envelope, data)
        if data['page'] == 3:
            raise RuntimeError('third member fails after DML')
        return result

    monkeypatch.setattr(worker.catalog, 'write', fail_third)
    with pytest.raises(RuntimeError, match='third member'):
        await worker.flush()
    assert (await query.list_news())['total'] == 0
    assert await store.client.xlen(store.stream) == 3
    assert not await worker.fingerprints.get('news', query.source, ['101', '102', '103'])
    assert not await store.client.get(f'{store.prefix}:archive:progress:news-test')
    monkeypatch.setattr(worker.catalog, 'write', original)
    archive, calls = mysql.archive, []

    async def capture(records):
        calls.append(len(records))
        return await archive(records)

    monkeypatch.setattr(mysql, 'archive', capture)
    await worker.flush()
    assert calls == [3]
    assert await store.client.xlen(store.stream) == 0
    assert {row['news_id'] for row in (await query.list_news())['rows']} == {101, 102, 103}
    for page in range(1, 4):
        await publish(100 + page, page=page, batch=batch, flush=False)

    def forbidden(*args):
        raise AssertionError('trusted batch must not access any SQL engine')

    for engine in (mysql.engine, mysql.read_engine, mysql.archive_engine):
        event.listen(engine, 'before_cursor_execute', forbidden)
    try:
        await worker.flush()
    finally:
        for engine in (mysql.engine, mysql.read_engine, mysql.archive_engine):
            event.remove(engine, 'before_cursor_execute', forbidden)
    assert calls == [3] and await store.client.xlen(store.stream) == 0


async def test_ack_loss_replays_exact_batch_without_duplicate_history_or_sql(news_db, monkeypatch):
    manager, publish, query = news_db
    worker = await manual_worker(manager)
    store, mysql = manager.registry.get('redis.store'), manager.registry.get('mysql.store')
    batch, ids = uuid4().hex, []
    for page in range(1, 5):
        value = await publish(100 + page, page=page, batch=batch, flush=False)
        ids.append(value.event_id + ':complete')
    original, acked = worker.acknowledge, []

    async def fail_ack(selected):
        acked.append(list(selected))
        raise ConnectionError('ack reply unavailable')

    monkeypatch.setattr(worker, 'acknowledge', fail_ack)
    with pytest.raises(ConnectionError, match='ack reply'):
        await worker.flush()
    assert len(acked) == 1 and len(acked[0]) == 4
    assert await store.client.xlen(store.stream) == 4
    assert (await query.list_news())['total'] == 4
    monkeypatch.setattr(worker, 'acknowledge', original)

    async def forbidden(*args):
        raise AssertionError('replay must use committed proofs')

    monkeypatch.setattr(mysql, 'archive', forbidden)
    await worker.flush()
    assert await store.client.xlen(store.stream) == 0
    history = await manager.registry.get('collection.records').list_archives('news-test')
    assert {row['id'] for row in history if row['status'] == 'complete'} == set(ids)
    assert sum(row['status'] == 'complete' for row in history) == 4
