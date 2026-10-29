"""Owned SQL/Redis namespace: source → normalization → shared archive → queries."""
import asyncio
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.yuanhang_limits.dataset import LimitDataset
from empire.features.yuanhang_limits.model import parse_reason
from empire.plugins.infra.redis_store import create_client
from tests.prefetch_source import prefetch_http
from tests.test_yuanhang_limits_source import detail, page, row

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Owned MySQL/Redis opt-in')]


@pytest.fixture
async def limits():
    cfg = load_config()
    manager = build_manager(cfg)
    try:
        await manager.start('collector.yuanhang_limits_limit_up_pool')
        c = manager.registry.get('collector.yuanhang_limits_limit_up_pool')
        q = manager.registry.get('yuanhang.limits.query')
        q.collection_plan = AsyncMock(return_value=dict(units=['2026-07-15'], cutoff='2026-07-15', remaining=0))
        c.http = prefetch_http(request=AsyncMock(side_effect=lambda *a, **k: httpx.Response(200, json=page([row()]))))
        yield manager, c, q
    finally:
        await manager.shutdown()
        client = create_client(cfg['redis'])
        prefix = cfg['redis']['namespace'] + ':'
        keys = [key async for key in client.scan_iter(match=prefix + '*')]
        assert ':test:' in prefix and all(key.startswith(prefix) for key in keys)
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def collect(c):
    return await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision(), history_only=True), 30)


async def test_explicit_pool_identity_resolves_missing_market_and_zero_time(limits):
    from empire.core.time import CHINA
    from empire.features.yuanhang_limits.repository import decode_member
    manager, c, q = limits
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, json=page([row('300362')]))
    await collect(c)
    assert await q.resolve_identities({'300362'}) == {'300362': '300362.SZ'}
    q.collection_plan.return_value = dict(units=['2026-07-16'], cutoff='2026-07-16', remaining=0)
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, json=page([
        {**row('300362'), 'market_id': None, 'first_limit_up_time': '0'}]))
    await collect(c)
    stored = (await q.members('2026-07-16', c.pool))['rows'][0]
    assert stored['identity_basis'] == 'pool_history' and stored['source_market_id'] is None
    assert stored['first_limit_up_time'].replace(tzinfo=CHINA).timestamp() == 0
    assert decode_member(stored)['first_limit_up_time'] == 0
    assert (await q.audit_pool('2026-07-16', c.pool))['complete']
    assert await manager.registry.get('redis.store').client.xlen(manager.registry.get('redis.store').stream) == 0
    q.collection_plan.return_value = dict(units=['2026-07-17'], cutoff='2026-07-17', remaining=0)
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, json=page([
        {**row('300362'), 'market_id': 17, 'first_limit_up_time': '0'}]))
    await collect(c)
    with pytest.raises(ValueError, match='身份冲突'):
        await q.resolve_identities({'300362'})


async def test_pool_real_archive_formal_query_hot_cold_repeat_zero_dml(limits):
    manager, c, q = limits
    await collect(c)
    assert (await q.audit_pool('2026-07-15', c.pool))['complete']
    assert (await q.members('2026-07-15', c.pool))['rows'][0]['unified_code'] == '000001.SZ'
    assert len((await q.history('000001.SZ', '2026-07-01', '2026-07-31'))['rows']) == 1
    writes, calls = [], []
    original = q.mysql.archive

    async def counted(*args, **kwargs):
        calls.append(1)
        return await original(*args, **kwargs)

    q.mysql.archive = counted

    def track(conn, cursor, statement, params, context, many):
        if 'yuanhang_limit_' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)

    event.listen(q.mysql.engine, 'before_cursor_execute', track)
    await collect(c)
    assert not calls and not writes
    await manager.registry.get('archive.worker').fingerprints.invalidate(LimitDataset(c.pool).FINGERPRINT_NAMESPACE, 'ths_yuanhang')
    await collect(c)
    assert calls and not writes
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0


async def test_same_count_changed_set_removes_only_target_pool_and_replay(limits):
    manager, c, q = limits
    await collect(c)
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, json=page([row('000002')]))
    await collect(c)
    assert [r['unified_code'] for r in (await q.members('2026-07-15', c.pool))['rows']] == ['000002.SZ']
    assert (await q.audit_pool('2026-07-15', c.pool))['complete']
    unit, stamp = await c.fetch('2026-07-15')
    unit['rows'][0]['name'] = '旧响应不能覆盖'
    stale = c.envelope(dict(batch_id='stale-limits', page=0), unit, stamp - timedelta(days=1))
    mapping = LimitDataset(c.pool)
    outcome = await manager.registry.get('archive.worker')._archive_data(stale, mapping.normalize(stale))
    assert outcome['written_count'] == 0
    assert (await q.members('2026-07-15', c.pool))['rows'][0]['name'] == '样本'


async def test_invalid_equal_count_duplicate_keeps_queue_checkpoint(limits):
    manager, c, q = limits
    await collect(c)
    before = await c.ingest.checkpoint(c.job_key)
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, json=page([row(), row()]))
    with pytest.raises(ValueError):
        await collect(c)
    assert await c.ingest.checkpoint(c.job_key) == before
    assert (await q.audit_pool('2026-07-15', c.pool))['complete']


async def test_empty_pool_is_source_observation_not_unknown_date_inference(limits):
    manager, c, q = limits
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, json=page([]))
    await collect(c)
    result = await q.audit_pool('2026-07-15', c.pool)
    assert result['complete'] and result['count'] == 0 and '不推定' in result['reason']
    assert not (await q.audit_pool('2026-07-14', c.pool))['complete']


@pytest.mark.parametrize('failure', ['transaction', 'acknowledgement'])
async def test_failed_archive_retains_message_and_replay_is_exact(limits, monkeypatch, failure):
    manager, c, q = limits
    archive = manager.registry.get('archive.worker')
    store = manager.registry.get('redis.store')
    await archive.stop()
    archive.stop_event.clear()
    unit, observed = await c.fetch('2026-07-15')
    cursor = dict(batch_id='recovery', page=0)
    envelope = c.envelope(cursor, unit, observed)
    state = await c.ingest.checkpoint(c.job_key)
    await c.ingest.publish_page([envelope], job_key=c.job_key,
                          expected_revision=state['revision'], cursor=dict(page=1))
    if failure == 'acknowledgement':
        original = archive.acknowledge
        monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=ConnectionError('after commit')))
    else:
        from empire.features.yuanhang_limits import dataset as module
        original = module.replace_pool

        def rollback(*args):
            original(*args)
            raise ConnectionError('before transaction commit')

        monkeypatch.setattr(module, 'replace_pool', rollback)
    with pytest.raises(ConnectionError):
        await archive.flush()
    assert await store.client.xlen(store.stream) == 1
    assert bool((await q.members('2026-07-15', c.pool))['rows']) == (failure == 'acknowledgement')
    writes = []

    def track(conn, cursor, statement, params, context, many):
        if 'yuanhang_limit_' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)

    event.listen(q.mysql.engine, 'before_cursor_execute', track)
    if failure == 'acknowledgement':
        monkeypatch.setattr(archive, 'acknowledge', original)
    else:
        monkeypatch.setattr(module, 'replace_pool', original)
    await archive.flush()
    assert bool(writes) == (failure == 'transaction')
    assert await store.client.xlen(store.stream) == 0
    assert (await q.audit_pool('2026-07-15', c.pool))['complete']


async def test_reason_shared_owner_and_unchanged_observation_protects_old_response(limits):
    manager, _, q = limits
    await manager.start('collector.yuanhang_limits_reason')
    c = manager.registry.get('collector.yuanhang_limits_reason')
    q.collection_plan.return_value = dict(units=[['2026-07-15', '000001.SZ']], cutoff='2026-07-15', remaining=0)
    c.http = prefetch_http(request=AsyncMock(side_effect=lambda *a, **k: httpx.Response(200, json=detail())))
    await collect(c)
    result = await q.reason('2026-07-15', '000001.SZ')
    assert result['reason_text'] == '正文'
    archive = manager.registry.get('archive.worker')
    await archive.fingerprints.invalidate(LimitDataset('reason').FINGERPRINT_NAMESPACE, 'ths_yuanhang')
    await collect(c)
    previous = parse_reason(detail('迟到修改'), '000001.SZ', '2026-07-15')
    stale = c.envelope(dict(batch_id='stale-reason', page=0), previous, datetime.now(UTC) - timedelta(days=1))
    mapping = LimitDataset('reason')
    assert (await archive._archive_data(stale, mapping.normalize(stale)))['written_count'] == 0
    assert (await q.reason('2026-07-15', '000001.SZ'))['reason_text'] == '正文'
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0
