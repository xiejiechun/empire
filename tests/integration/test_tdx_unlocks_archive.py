"""List/detail→Redis→shared transaction→official query and exact set audit."""
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
from tests.prefetch_source import prefetch_http
from tests.test_tdx_unlocks import MONTH, detail, normalized, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to private SQL/Redis')]


@pytest.fixture
async def monthly():
    cfg = copy.deepcopy(load_config())
    manager, store = build_manager(cfg), None
    try:
        await manager.start('collector.tdx_unlocks')
        c, q = manager.registry.get('collector.tdx_unlocks'), manager.registry.get('unlocks.tdx_query')
        store = manager.registry.get('redis.store')
        c.http = prefetch_http(request=AsyncMock(side_effect=lambda *a, **kw: httpx.Response(200,
            json=source() if json.loads(kw['content'])['Params'][0] == '0' else detail())), response_policy=lambda _: None)
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
    return await asyncio.wait_for(c.execute(start_month=MONTH, end_month=MONTH,
        baseline_revision=await c.checkpoint_revision()), 25)


async def test_parent_shared_group_query_hot_cold_revision_stale_replay(monthly):
    manager, c, q, store = monthly
    await collect(c)
    rows = (await q.list_records())['rows']
    assert len(rows) == 2 and len(await q.details(rows[0]['group_key'])) == 1
    page = await q.list_records(limit=1)
    assert page['next'] and (await q.list_records(after=page['next'], limit=1))['rows'][0]['record_key'] != page['rows'][0]['record_key']
    checks = {v.criterion: v.status for v in await q.preparation_check(dict(start=MONTH, end='2020-01-31'))}
    assert checks['coverage'] == checks['keys'] == checks['fields'] == 'pass'
    assert checks['temporal'] == 'fail'
    # A finite acceptance sample never proves the default full-history range.
    assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'fail'
    archive, dml, calls = manager.registry.get('archive.worker'), [], []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'restricted_share_unlock' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            dml.append(statement)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    original = q.mysql.archive
    async def counted(records):
        calls.append(records)
        return await original(records)
    q.mysql.archive = counted
    try:
        await collect(c)
        assert not dml and not calls
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        await collect(c)
        assert not dml and calls
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(200,
            json=source(revised=True) if json.loads(kw['content'])['Params'][0] == '0' else detail(revised=True))
        await collect(c)
        assert dml and len((await q.list_records())['rows']) == 2
        p, d = normalized(revised=True)
        # Detail correction is separate from list correction.
        from empire.plugins.collectors.tdx_unlock_source import parse_detail
        d = parse_detail(detail(revised=True), p[0])
        cursor = dict(batch_id='replay', page=0)
        prior = c.envelope(MONTH + '|SH', p, d, cursor, datetime.now(UTC))
        before = len(dml)
        stale = prior.model_copy(update={'observed_at': datetime.now(UTC) - timedelta(days=1)})
        assert (await archive._archive_data(stale, q.mapping.normalize(stale)))['written_count'] == 0
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        assert (await archive._archive_data(prior, q.mapping.normalize(prior)))['written_count'] == 0
        assert len(dml) == before and await store.client.xlen(store.stream) == 0
    finally:
        q.mysql.archive = original
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


@pytest.mark.parametrize('failure', ['sql', 'ack'])
async def test_transaction_and_commit_replay_queue_cleanup(monthly, monkeypatch, failure):
    manager, c, q, store = monthly
    archive = manager.registry.get('archive.worker')
    owner, method = (q.mysql, 'archive') if failure == 'sql' else (archive, 'acknowledge')
    original, attempted = getattr(owner, method), asyncio.Event()
    async def fail(*args, **kw):
        attempted.set()
        raise RuntimeError('owned test failure')
    monkeypatch.setattr(owner, method, fail)
    task = asyncio.create_task(collect(c))
    try:
        await asyncio.wait_for(attempted.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await store.client.xlen(store.stream) > 0
        monkeypatch.setattr(owner, method, original)
        archive.request_flush()
        await collect(c)
        assert await store.client.xlen(store.stream) == 0
        assert len((await q.list_records())['rows']) == 2
        await store.client.delete(c.ingest._checkpoint_key(c.job_key))
        await collect(c)
        assert len((await q.list_records())['rows']) == 2
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_missing_association_same_count_wrong_set_repair_and_source_empty(monthly):
    manager, c, q, store = monthly
    await collect(c)
    cache = manager.registry.get('archive.worker').fingerprints
    await cache.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
    def damage():
        with q.mysql.engine.begin() as conn:
            conn.execute(text("UPDATE restricted_share_unlock_detail SET holder='同数异集损坏' LIMIT 1"))
    await q.mysql.control(damage)
    assert next(v for v in await q.preparation_check(dict(start=MONTH, end='2020-01-31')) if v.criterion == 'coverage').status == 'fail'
    await collect(c)
    assert next(v for v in await q.preparation_check(dict(start=MONTH, end='2020-01-31')) if v.criterion == 'coverage').status == 'pass'
    optional = source()
    for row in optional['ResultSets'][0]['Content']:
        row[2] = None
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200,
        json=optional if json.loads(kw['content'])['Params'][0] == '0' else detail())
    await collect(c)
    checks = {v.criterion: v.status for v in await q.preparation_check(dict(start=MONTH, end='2020-01-31'))}
    assert checks['fields'] == checks['quality'] == 'pass'  # Optional source names do not block analysis.
    assert all(r['name'] is None for r in (await q.list_records())['rows'])
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200,
        json=source() if json.loads(kw['content'])['Params'][0] == '0' else detail(empty=True))
    await collect(c)
    rows = (await q.list_records())['rows']
    assert len(rows) == 2 and not await q.details(rows[0]['group_key'])
    checks = {v.criterion: v.status for v in await q.preparation_check(dict(start=MONTH, end='2020-01-31'))}
    assert checks['coverage'] == 'pass' and checks['fields'] == checks['quality'] == 'fail'
    assert await store.client.xlen(store.stream) == 0
