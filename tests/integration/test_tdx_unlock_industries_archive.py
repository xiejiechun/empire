"""Industry response→Redis→shared archive→formal SQL queries and repairs."""
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
from tests.test_tdx_unlock_industries import MONTHS, directory, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to private SQL/Redis')]


@pytest.fixture
async def monthly():
    cfg = copy.deepcopy(load_config())
    manager, store = build_manager(cfg), None
    try:
        await manager.start('collector.tdx_unlock_industries')
        c, q = manager.registry.get('collector.tdx_unlock_industries'), manager.registry.get('unlock_industries.tdx_query')
        store = manager.registry.get('redis.store')
        def response(*a, **kw):
            params = json.loads(kw['content'])['Params']
            return httpx.Response(200, json=directory() if params[0] == 'dxfhy' else source(params[0][:4] + '-' + params[0][4:] + '-01'))
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


async def test_hot_cold_repeat_revision_old_basis_wrong_set_and_old_month_retention(monthly):
    manager, c, q, store = monthly
    await collect(c)
    rows = (await q.list_records())['rows']
    assert len(rows) == 4 and rows[0]['basis_date'] == '2026-10-13'
    page = await q.list_records(limit=1)
    assert page['next'] and (await q.list_records(after=page['next'], limit=1))['rows'][0] != page['rows'][0]
    assert len((await q.list_records(industry='航空'))['rows']) == 2
    assert all(v.status == 'pass' for v in await q.preparation_check() if v.criterion != 'temporal')
    archive, dml, calls = manager.registry.get('archive.worker'), [], []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'restricted_share_unlock_industry' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            dml.append(statement)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    original = q.mysql.archive
    async def counted(records):
        calls.append(records)
        return await original(records)
    q.mysql.archive = counted
    try:
        await collect(c)
        assert not calls and not dml
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        await collect(c)
        assert calls and not dml
        params = dict(batch_id='revision', basis_date='2026-10-13', page=0)
        from empire.features.unlock_industries.source import parse_month
        value = c.envelope(params, MONTHS[0], parse_month(source(revised=True), MONTHS[0], params['basis_date']))
        assert (await archive._archive_data(value, q.mapping.normalize(value)))['written_count'] == 1
        before = len(dml)
        stale = value.model_copy(update={'observed_at': datetime.now(UTC) - timedelta(days=1)})
        assert (await archive._archive_data(stale, q.mapping.normalize(stale)))['written_count'] == 0
        old = {**params, 'basis_date': '2026-10-12'}
        old_basis = c.envelope(old, MONTHS[0], parse_month(source(), MONTHS[0], old['basis_date']))
        assert (await archive._archive_data(old_basis, q.mapping.normalize(old_basis)))['written_count'] == 0
        assert len(dml) == before
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        def damage():
            with q.mysql.engine.begin() as conn:
                conn.execute(text("UPDATE restricted_share_unlock_industry SET shares=NULL WHERE industry='航空' LIMIT 1"))
        await q.mysql.control(damage)
        assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'fail'
        await collect(c)
        assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'pass'
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        def wrong_set():
            with q.mysql.engine.begin() as conn:
                conn.execute(text("UPDATE restricted_share_unlock_industry SET industry='损坏集合' WHERE industry='航空' LIMIT 1"))
        await q.mysql.control(wrong_set)
        assert next(v for v in await q.preparation_check() if v.criterion == 'keys').status == 'fail'
        await collect(c)
        assert next(v for v in await q.preparation_check() if v.criterion == 'keys').status == 'pass'
        original_source = c.http.request.side_effect
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=directory(months=[MONTHS[1]])) if json.loads(kw['content'])['Params'][0] == 'dxfhy' else original_source(*a, **kw)
        await collect(c)
        assert len((await q.list_records())['rows']) == 4  # Old month is retained.
        assert await store.client.xlen(store.stream) == 0
    finally:
        q.mysql.archive = original
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


@pytest.mark.parametrize('failure', ['sql', 'ack'])
async def test_failed_archive_and_commit_replay_keep_queue_then_clean_and_redis_loss(monthly, monkeypatch, failure):
    manager, c, q, store = monthly
    archive = manager.registry.get('archive.worker')
    owner, method = (q.mysql, 'archive') if failure == 'sql' else (archive, 'acknowledge')
    original, attempted = getattr(owner, method), asyncio.Event()
    async def fail(*args, **kw):
        attempted.set()
        raise RuntimeError('owned integration failure')
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
        await store.client.delete(c.ingest._checkpoint_key(c.job_key))
        await collect(c)
        assert len((await q.list_records())['rows']) == 4
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
