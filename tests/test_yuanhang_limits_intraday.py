"""Volatile snapshots, clock boundaries and guarded publication contracts."""
import asyncio
import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from empire.contracts.data import BackpressureError
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.yuanhang_limits.intraday import session_phase
from empire.features.yuanhang_limits.intraday_store import IntradayStore
from empire.features.yuanhang_limits.model import member
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.ingest import IngestPlugin
from tests.test_yuanhang_limits_source import row


@pytest.mark.parametrize(('clock', 'trade', 'expected'), [
    ('09:24', 1, 'idle'), ('09:25', 1, 'live'), ('11:30', 1, 'live'),
    ('11:31', 1, 'idle'), ('12:59', 1, 'idle'), ('13:00', 1, 'live'),
    ('15:05', 1, 'live'), ('15:06', 1, 'idle'), ('15:29', 1, 'idle'),
    ('15:30', 1, 'daily'), ('09:30', 0, 'idle'), ('18:00', 0, 'daily'),
])
def test_trading_session_boundary(clock, trade, expected):
    assert session_phase(datetime.fromisoformat('2026-10-27T' + clock).replace(tzinfo=CHINA), trade) == expected


def test_missing_calendar_cannot_be_inferred_as_closed():
    with pytest.raises(ValueError, match='正式日历'):
        session_phase(datetime.now(CHINA), None)


@pytest.mark.parametrize(('clock', 'accepted'), [('10:00', False), ('15:29', False), ('15:30', True)])
def test_archive_boundary_rejects_intraday_even_if_enqueued_by_mistake(clock, accepted):
    from empire.features.yuanhang_limits.dataset import LimitDataset
    from tests.test_yuanhang_limits_collector import setup_collector
    c, _, _, _ = setup_collector([])
    observed = datetime.fromisoformat('2026-10-27T' + clock).replace(tzinfo=CHINA)
    event = c.envelope(dict(page=0, batch_id='test'), unit('2026-10-27'), observed)
    if accepted:
        assert LimitDataset(c.pool).normalize(event)['row_count'] == 1
    else:
        with pytest.raises(ValueError, match='不得进入MySQL'):
            LimitDataset(c.pool).normalize(event)


@pytest.mark.asyncio
async def test_sampling_cannot_publish_or_advance_daily_checkpoint():
    from empire.features.yuanhang_limits.intraday import collect_live
    from tests.test_yuanhang_limits_collector import setup_collector
    now = datetime.now(CHINA)
    c, state, events, _ = setup_collector([now.date().isoformat()])
    c.live_store = SimpleNamespace(save=AsyncMock(return_value=dict(changed=True, stale=False, evicted=0)))
    async def volatile(project, commit):
        return await commit()
    c.ingest.publish_volatile = volatile
    result = await collect_live(c, now)
    assert result['storage'] == 'redis_only' and result['queued_messages'] == 0
    assert state == {'revision': 0, 'cursor': {}} and not events
    c.confirmation.page_status.assert_not_awaited()
    c.live_store.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_live_failure_preserves_snapshot_and_durable_checkpoint():
    from empire.features.yuanhang_limits.intraday import collect_live
    from tests.test_yuanhang_limits_collector import setup_collector
    now = datetime.now(CHINA)
    c, state, events, _ = setup_collector([now.date().isoformat()])
    c.fetch = AsyncMock(side_effect=ValueError('membership changed'))
    c.live_store = SimpleNamespace(save=AsyncMock())
    with pytest.raises(ValueError, match='membership changed'):
        await collect_live(c, now)
    c.live_store.save.assert_not_awaited()
    assert state['revision'] == 0 and not events


@pytest.mark.asyncio
async def test_daily_resume_does_not_mark_today_when_older_plan_completed(monkeypatch):
    from empire.features.yuanhang_limits import intraday
    monkeypatch.setattr(intraday, 'phase', AsyncMock(return_value='daily'))
    c = SimpleNamespace(pool='limit_up_pool', stats={},
        plan_options=lambda scope=None: {"scope": scope},
        job_key="pool", ingest=SimpleNamespace(checkpoint=AsyncMock(return_value=dict(cursor={}, revision=0))),
        live_store=SimpleNamespace(maintenance_day=AsyncMock(return_value=None), mark_maintenance=AsyncMock()),
        query=SimpleNamespace(collection_plan=AsyncMock(return_value=dict(cutoff='2026-10-27', units=[]))),
        _execute=AsyncMock(return_value=dict(cutoff='2026-10-26')))
    await intraday.dispatch(c, fresh=False, baseline_revision=0)
    c.live_store.mark_maintenance.assert_not_awaited()
    c._execute.return_value = dict(cutoff='2026-10-27')
    await intraday.dispatch(c, fresh=False, baseline_revision=0)
    c.live_store.mark_maintenance.assert_awaited_once()


@pytest.mark.asyncio
async def test_volatile_admission_rechecks_isolation_after_capacity_wait():
    p = IngestPlugin({})
    p.catalog = SimpleNamespace(contributions=[SimpleNamespace(projects={'job': 'pool'})])
    p.archive = SimpleNamespace(blocked=False, blocked_projects=set())
    async def capacity(*args):
        p.archive.blocked_projects.add('pool')
    p._ensure_capacity_locked = capacity
    commit = AsyncMock()
    with pytest.raises(BackpressureError):
        await p.publish_volatile('pool', commit)
    commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_volatile_success_not_reclassified_after_dispatch():
    p = IngestPlugin({})
    p.catalog = SimpleNamespace(contributions=[SimpleNamespace(projects={'job': 'pool'})])
    p.archive = SimpleNamespace(blocked=False, blocked_projects=set())
    p._ensure_capacity_locked = AsyncMock()
    async def commit():
        p.archive.blocked = True
        return 'committed'
    assert await p.publish_volatile('pool', commit) == 'committed'
    with pytest.raises(ValueError, match='未登记'):
        await p.publish_volatile('other', commit)


def unit(day, code='000001'):
    raw = row()
    raw.update(code=code, market_id=33, first_limit_up_time=None)
    return dict(trade_date=day, pool_type='limit_up_pool', filter='HS,GEM2STAR',
                source_total=1, rows=[member(raw, day)])


@pytest.mark.skipif(os.environ.get('EMPIRE_REDIS_REAL') != '1', reason='Explicit isolated Redis snapshot test')
@pytest.mark.asyncio
async def test_real_redis_changes_old_response_retention_and_fixed_replay(monkeypatch):
    import empire.features.yuanhang_limits.intraday_store as module
    client = create_client(load_config()['redis'])
    prefix = 'empire:test:' + uuid4().hex
    store = IntradayStore(SimpleNamespace(client=client, prefix=prefix))
    keys = store.keys('limit_up_pool')
    stamp = datetime.now(CHINA) - timedelta(minutes=5)
    day = stamp.date().isoformat()
    first = unit(day)
    try:
        a = await store.save(first, stamp, stamp + timedelta(seconds=2))
        assert a['changed']
        initial_version = (await store.read('limit_up_pool', day))['version']
        initial_ttl = await client.pttl(store.body_key('limit_up_pool', initial_version))
        assert not (await store.save(first, stamp + timedelta(seconds=3), stamp + timedelta(seconds=4)))['changed']
        later_ttl = await client.pttl(store.body_key('limit_up_pool', initial_version))
        assert 0 <= initial_ttl - later_ttl < 1000  # No renewal of old snapshot expiry.
        assert await client.zcard(keys[1]) == 1
        assert (await store.save(unit(day, '000002'), stamp, stamp + timedelta(seconds=1)))['stale']
        assert (await store.read('limit_up_pool', day))['unit'] == first
        assert await store.read('limit_up_pool', day, at=(stamp + timedelta(seconds=1)).strftime('%H:%M:%S.%f')) is None
        fixed = (await store.read('limit_up_pool', day))['version']
        second = unit(day, '000002')
        assert (await store.save(second, stamp + timedelta(seconds=5), stamp + timedelta(seconds=6)))['changed']
        assert (await store.read('limit_up_pool', day, version=fixed))['unit'] == first
        assert (await store.read('limit_up_pool', day))['unit'] == second
        listing = await store.timeline('limit_up_pool', day, limit=1)
        assert len(listing['versions']) == 1 and listing['next']
        assert len((await store.timeline('limit_up_pool', day, before=listing['next']))['versions']) == 1
        monkeypatch.setattr(module, 'MAX_SNAPSHOTS', 2)
        assert (await store.save(unit(day, '000003'), stamp + timedelta(seconds=7), stamp + timedelta(seconds=8)))['evicted'] == 1
        assert await store.read('limit_up_pool', day, version=fixed) is None
        assert await client.zcard(keys[1]) == 2
        body_keys = [store.body_key('limit_up_pool', v) for v in await client.zrange(keys[1], 0, -1)]
        assert 0 < await client.ttl(body_keys[0]) <= module.TTL
        bodies = await client.mget(body_keys)
        assert int(await client.hget(keys[2], 'bytes')) == sum(len(b.encode()) for b in bodies)
        assert not await client.exists(prefix + ':ingest')
        await client.delete(*keys, *body_keys)  # Exactly this UUID-owned test's keys.
        assert await store.read('limit_up_pool', day) is None
        assert (await store.save(second, stamp + timedelta(seconds=9), stamp + timedelta(seconds=10)))['changed']
        assert await client.zcard(keys[1]) == 1
        latest = (await store.read('limit_up_pool', day))['version']
        await client.expire(store.body_key('limit_up_pool', latest), 1)
        await asyncio.sleep(1.1)
        assert await store.read('limit_up_pool', day) is None
    finally:
        owned = [k async for k in client.scan_iter(match=prefix + ':*')]
        assert all(k.startswith(prefix + ':') for k in owned)
        if owned:
            await client.delete(*owned)
        await client.aclose()


def test_schedule_change_preserves_network_retry_and_disable_preferences():
    from scripts.configure_yuanhang_intraday import intraday_policy
    policy = intraday_policy(dict(mode='daily', daily_time='19:30', interval_seconds=86400,
                                  use_proxy=False, proxy_fallback=False, request_retries=0, enabled=False))
    assert policy['mode'] == 'interval' and policy['interval_seconds'] == 60
    assert not policy['use_proxy'] and not policy['proxy_fallback'] and not policy['enabled']
    assert policy['request_retries'] == 0 and policy['daily_time'] == '19:30'


@pytest.mark.skipif(os.environ.get('EMPIRE_REDIS_REAL') != '1', reason='Explicit isolated Redis replay test')
@pytest.mark.asyncio
async def test_real_redis_paged_interval_label_and_replay_page_are_immutable():
    from copy import deepcopy

    from empire.features.yuanhang_limits.intraday_query import browse_live
    client = create_client(load_config()['redis'])
    prefix = 'empire:test:' + uuid4().hex
    redis = SimpleNamespace(client=client, prefix=prefix)
    store = IntradayStore(redis)
    query = SimpleNamespace(context=SimpleNamespace(optional=lambda _: redis))
    stamp = datetime.now(CHINA) - timedelta(minutes=1)
    day = stamp.date().isoformat()
    large = unit(day)
    prototype = large['rows'][0]
    large['rows'] = [dict(deepcopy(prototype), unified_code=f'{i:06d}.SZ') for i in range(1, 403)]
    large['source_total'] = len(large['rows'])
    filters = (3, 'limit_up_pool', '', day, '', '')
    try:
        await store.save(large, stamp, stamp + timedelta(seconds=1))
        first = await browse_live(query, filters, None)
        assert len(first['rows']) == 200 and '非同一瞬间冻结' in first['message']
        await store.save(unit(day, '000999'), stamp + timedelta(seconds=2), stamp + timedelta(seconds=3))
        second = await browse_live(query, filters, first['next'])
        assert len(second['rows']) == 200 and second['rows'][0]['unified_code'] == '000201.SZ'
        third = await browse_live(query, filters, second['next'])
        assert len(third['rows']) == 2 and third['next'] is None
        latest = await browse_live(query, filters, None)
        assert latest['rows'][0]['unified_code'] == '000999.SZ'
        await client.delete(store.body_key('limit_up_pool', first['next'][0]))
        expired = await browse_live(query, filters, first['next'])
        assert not expired['rows'] and '无保留快照' in expired['message']
    finally:
        owned = [k async for k in client.scan_iter(match=prefix + ':*')]
        assert all(k.startswith(prefix + ':') for k in owned)
        if owned:
            await client.delete(*owned)
        await client.aclose()


@pytest.mark.skipif(os.environ.get('EMPIRE_REDIS_REAL') != '1', reason='Explicit Redis holiday expiry test')
@pytest.mark.asyncio
async def test_expired_index_with_retained_maintenance_marker_recovers_byte_budget(monkeypatch):
    from redis.exceptions import ResponseError

    import empire.features.yuanhang_limits.intraday_store as module

    client = create_client(load_config()['redis'])
    prefix = 'empire:test:' + uuid4().hex
    store = IntradayStore(SimpleNamespace(client=client, prefix=prefix))
    pool = 'limit_up_pool'
    keys = store.keys(pool)
    stamp = datetime.now(CHINA) - timedelta(seconds=5)
    day = stamp.date().isoformat()
    try:
        await store.save(unit(day), stamp, stamp + timedelta(seconds=1))
        old = (await store.read(pool, day))['version']
        size = int(await client.hget(keys[2], 'bytes'))
        monkeypatch.setattr(module, 'MAX_BYTES', size + 100)
        await client.expire(store.body_key(pool, old), 1)
        await client.expire(keys[1], 1)
        await store.mark_maintenance(pool, day)
        await asyncio.sleep(1.1)
        assert await client.exists(keys[2]) and not await client.exists(keys[1])
        now = datetime.now(CHINA)
        assert (await store.save(unit(day, '000002'), now, now))['changed']
        current = await store.read(pool, day)
        assert current['unit']['rows'][0]['unified_code'] == '000002.SZ'
        assert await client.hget(keys[2], 'size:' + old) is None
        assert int(await client.hget(keys[2], 'bytes')) == len(await client.get(store.body_key(pool, current['version'])))
        # Losing only the index while live bodies exist cannot authorize extra memory.
        await client.delete(keys[1])
        with pytest.raises(ResponseError, match='index missing'):
            await store.save(unit(day, '000003'), now + timedelta(seconds=1), now + timedelta(seconds=1))
        assert await client.exists(store.body_key(pool, current['version']))
    finally:
        owned = [k async for k in client.scan_iter(match=prefix + ':*')]
        assert all(k.startswith(prefix + ':') for k in owned)
        if owned:
            await client.delete(*owned)
        await client.aclose()
