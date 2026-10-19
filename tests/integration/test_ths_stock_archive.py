import asyncio
import os
from types import SimpleNamespace

import pytest
from sqlalchemy import event
from test_stock_archive import ROWS, stock_database  # noqa: F401

from empire.features.stocks.ths_collector import ThsUniverseCollector
from tests.test_ths_universe import Source, document

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


async def test_ths_source_to_query_cold_hot_repair_replay_and_cross_source_old_version(stock_database, monkeypatch):  # noqa: F811
    snapshot, publish, query, manager = stock_database
    # Old directory first; the new source must fill names and replace the complete set.
    older = snapshot()
    await publish('page', older, page=1, rows=ROWS)
    await publish('complete', older, pages=1, collected=2, count_after=2, terminal_rows=[])
    query.project_id = 'current'
    ingest, archive = manager.registry.get('ingest.publish'), manager.registry.get('archive.worker')
    store, mysql = manager.registry.get('redis.store'), manager.registry.get('mysql.store')
    collector = ThsUniverseCollector()
    await manager.start('infra.http')
    await collector.start(SimpleNamespace(get=manager.registry.get))
    collector.http = Source(document(('920627', '000001', '688196')))
    collector.session = SimpleNamespace(headers=lambda referer: {'Referer': referer})
    await asyncio.wait_for(collector.execute(), 10)
    result = await query.list_stocks()
    assert {r['unified_code'] for r in result['rows']} == {'920627.BJ', '000001.SZ', '688196.SH'}
    assert {r['source'] for r in result['rows']} == {'ths'}
    assert await store.client.xlen(store.stream) == 0
    assert len(collector.http.calls) == 1
    changes = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        upper = statement.strip().upper()
        if upper.startswith(('INSERT INTO STOCK ', 'DELETE FROM STOCK', 'UPDATE STOCK ')):
            changes.append(statement)
    event.listen(mysql.engine, 'before_cursor_execute', capture)
    try:
        # Trusted common-directory proof must avoid all MySQL, not just business DML.
        async def forbidden(*args, **kwargs):
            raise AssertionError('Hot directory proof must avoid MySQL')
        with monkeypatch.context() as patch:
            patch.setattr(mysql, 'archive', forbidden)
            patch.setattr(mysql, 'control', forbidden)
            await asyncio.wait_for(collector.execute(baseline_revision=await collector.checkpoint_revision()), 10)
        assert await store.client.xlen(store.stream) == 0
        await archive.fingerprints.invalidate('stocks', 'current')
        await asyncio.wait_for(collector.execute(baseline_revision=await collector.checkpoint_revision()), 10)
        assert not changes
        # Replay after SQL commit/cache failure leaves all messages until successful retry.
        original = archive.fingerprints.put
        failed = False
        async def fail_once(*args, **kwargs):
            nonlocal failed
            if not failed:
                failed = True
                raise ConnectionError('injected post-commit failure')
            return await original(*args, **kwargs)
        monkeypatch.setattr(archive.fingerprints, 'put', fail_once)
        collector.http.content = document(('920627', '000002', '688196'))
        await asyncio.wait_for(collector.execute(baseline_revision=await collector.checkpoint_revision()), 15)
        assert failed and await store.client.xlen(store.stream) == 0
        latest = {r['unified_code'] for r in (await query.list_stocks())['rows']}
        assert latest == {'920627.BJ', '000002.SZ', '688196.SH'}
        changes.clear()
        await archive.fingerprints.invalidate('stocks', 'current')
        # The original Sina batch is stale even after the common proof is removed.
        await publish('page', older, page=1, rows=ROWS)
        await publish('complete', older, pages=1, collected=2, count_after=2, terminal_rows=[])
        for _ in range(20):
            await archive.flush()
            if not await store.client.xlen(store.stream):
                break
            await asyncio.sleep(.01)
        assert not changes and await store.client.xlen(store.stream) == 0
        assert {r['unified_code'] for r in (await query.list_stocks())['rows']} == latest
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', capture)
    assert (await ingest.checkpoint('ths-universe-v1'))['cursor']['phase'] == 'complete'
