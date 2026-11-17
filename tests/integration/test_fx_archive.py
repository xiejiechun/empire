"""Private SQL/Redis pipeline, replay and a genuinely SQL-free realtime round."""
import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.bootstrap import build_manager
from empire.contracts.collector import CollectionSourceGap
from empire.core.config import load_config
from empire.features.fx.contract import DAILY_JOB, SYMBOLS
from empire.features.fx.dataset import FINGERPRINT_NAMESPACE
from tests.prefetch_source import prefetch_http
from tests.test_fx import CODE, ROWS, envelope, live_source
from tests.test_fx import collector as fake_collector

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit independent SQL')]


@pytest.fixture
async def fx():
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:fx:' + uuid4().hex
    m, store = build_manager(cfg), None
    try:
        await m.start('collector.ths_fx_daily')
        c, q, store = [m.registry.get(k) for k in ('collector.ths_fx_daily', 'fx.daily.query', 'redis.store')]
        c.http, c.selected_codes = fake_collector().http, [CODE]
        async def publish(e):
            state = await c.ingest.checkpoint(DAILY_JOB)
            await c.ingest.publish_page([e], job_key=DAILY_JOB, expected_revision=state['revision'], cursor=dict(test=True))
            await m.registry.get('archive.worker').flush()
        yield m, c, q, store, publish
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


async def test_daily_pipeline_no_change_revision_old_replay_and_recovery(fx, monkeypatch):
    m, c, q, store, publish = fx
    result = await asyncio.wait_for(c.execute(), 30)
    assert result['collected'] == 3 and await store.client.xlen(store.stream) == 0
    rows = (await q.browse(CODE))['rows']
    assert [r['trade_date'].isoformat() for r in rows] == [r[0] for r in ROWS[::-1]]
    page = await q.browse(CODE, limit=1)
    assert len((await q.browse(CODE, after=page['next']))['rows']) == 2
    await store.client.delete(c.ingest._checkpoint_key(DAILY_JOB))
    c.http.request.reset_mock()
    await c.execute()
    assert c.http.request.await_count == 2
    archive, writes = m.registry.get('archive.worker'), []
    def capture(conn, cursor, sql, *args):
        if ('fx_daily_price' in sql or 'fx_price_year' in sql) and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(Engine, 'before_cursor_execute', capture)
    try:
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, 'ths')
        now = datetime.now(UTC)
        base = envelope().model_copy(update={'observed_at': now})
        await publish(base)
        await publish(base.model_copy(update={'observed_at': now + timedelta(seconds=1)}))
        assert not writes and await store.client.xlen(store.stream) == 0
        revised = copy.deepcopy(ROWS[:2])
        revised[1][4] = '6.9'
        changed = envelope(revised).model_copy(update={'observed_at': now + timedelta(seconds=2)})
        await publish(changed)
        assert len(writes) == 2
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, 'ths')
        await publish(base)
        assert len(writes) == 2
        assert str((await q.browse(CODE, start='2025-12-31', end='2025-12-31'))['rows'][0]['close']) == '6.9000000000'
        # A SQL commit followed by Redis confirmation failure is safely replayed.
        original = archive.fingerprints.put
        async def fail(*args, **kwargs):
            raise RuntimeError('Redis confirmation unavailable')
        monkeypatch.setattr(archive.fingerprints, 'put', fail)
        revised[1][4] = '6.8'
        with pytest.raises(RuntimeError):
            await publish(envelope(revised).model_copy(update={'observed_at': now + timedelta(seconds=3)}))
        count = len(writes)
        assert await store.client.xlen(store.stream) == 1
        monkeypatch.setattr(archive.fingerprints, 'put', original)
        await archive.flush()
        assert len(writes) == count and await store.client.xlen(store.stream) == 0
    finally:
        event.remove(Engine, 'before_cursor_execute', capture)


async def test_live_latest_values_only_zero_sql_and_failure_preserves_old(fx):
    m, _, _, store, _ = fx
    await m.start('collector.ths_fx_live')
    c = m.registry.get('collector.ths_fx_live')
    async def request(method, url, **kw):
        code = url.split('wh_')[1].split('/')[0]
        return httpx.Response(200, content=live_source(code).encode())
    c.http = prefetch_http(request=request, response_policy=lambda _: None)
    def reject(*args):
        raise AssertionError('Realtime round accessed SQL')
    event.listen(Engine, 'before_cursor_execute', reject)
    try:
        assert await c.checkpoint_revision() == 0
        await c.execute()
        latest = m.registry.get('fx.latest.query')
        first = await latest.browse()
        assert len(first['rows']) == 12 and await store.client.hlen(latest.key) == 24
        before = await store.client.hgetall(latest.key)
        await c.execute()
        assert await store.client.hlen(latest.key) == 24
        assert await store.client.xlen(store.stream) == 0
        code = SYMBOLS.keys().__iter__().__next__()
        import json
        quote = json.loads(before[code])
        assert not await latest.save(quote)  # late response does not replace newer sample
        assert len(await store.client.keys(store.prefix + ':fx:*')) == 1
        async def broken(*args, **kwargs):
            raise ValueError('bounded source failure')
        c.http.request = broken
        with pytest.raises(ValueError):
            await c.execute()
        assert len((await latest.browse())['rows']) == 12
        assert await store.client.xlen(store.stream) == 0
        await store.client.delete(latest.key)
        c.http.request = request
        await c.execute()
        assert len((await latest.browse())['rows']) == 12
    finally:
        event.remove(Engine, 'before_cursor_execute', reject)


async def test_stale_daily_cache_reconciles_through_archive_and_conflict_preserves_sql(fx, monkeypatch):
    from types import SimpleNamespace

    from tests.test_fx import source, today_source
    from tests.test_fx_verification import CLOSED, CURRENT, NOW, OLD

    monkeypatch.setattr('empire.features.fx.transport.datetime', SimpleNamespace(now=lambda _: NOW + timedelta(seconds=1)))

    _, c, q, store, publish = fx
    await publish(envelope([OLD], year=2026, source_count=1,
                           start='2026-11-09', end='2026-11-09').model_copy(
                               update={'observed_at': NOW}))
    assert str((await q.browse(CODE))['rows'][0]['close']) == '6.6713100000'
    unresolved = False
    def request(method, url, **kwargs):
        if '/today.js' in url:
            body = today_source(CURRENT)
        elif '/last.js' in url:
            body = source(rows=[CLOSED], start='20261109', year={'2026': 2}, total='2')
        else:
            body = source(2026, [OLD if unresolved else CLOSED, CURRENT])
        return httpx.Response(200, content=body.encode())
    c.http.request.side_effect = request
    assert (await c.execute())['phase'] == 'complete'
    rows = (await q.browse(CODE))['rows']
    assert len(rows) == 1 and str(rows[0]['close']) == '6.6694500000'
    assert str(rows[0]['low']) == '6.6692500000'
    assert await store.client.xlen(store.stream) == 0
    unresolved = True
    before = await c.ingest.checkpoint(DAILY_JOB)
    with pytest.raises(CollectionSourceGap, match='USDCNH'):
        await c.execute(baseline_revision=before['revision'])
    assert await c.ingest.checkpoint(DAILY_JOB) == before
    assert (await q.browse(CODE))['rows'] == rows
    assert await store.client.xlen(store.stream) == 0
