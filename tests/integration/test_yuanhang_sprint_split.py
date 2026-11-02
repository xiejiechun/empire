"""One owner retains separate rounds and late-response version safety."""
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event

from empire.features.yuanhang_limits.contract import POOLS, SOURCE
from empire.features.yuanhang_limits.dataset import LimitDataset
from empire.features.yuanhang_limits.proofs import pool_versions
from empire.features.yuanhang_limits.query import LimitQuery
from tests.integration.test_yuanhang_limits_archive import collect
from tests.integration.test_yuanhang_limits_archive import limits as limits
from tests.integration.test_yuanhang_limits_archive import pytestmark as pytestmark
from tests.integration.test_yuanhang_limits_plans import calendar
from tests.prefetch_source import prefetch_http
from tests.test_yuanhang_limits_source import page, row


@pytest.fixture(params=tuple(POOLS))
async def sprint(limits, request):
    manager, _, query = limits
    capability = 'collector.yuanhang_limits_' + request.param
    await manager.start(capability)
    collector = manager.registry.get(capability)
    collector.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, json=page([row()]))))
    return manager, collector, query



async def test_separate_runs_share_cache_cold_proofs_reject_late_response_and_clean_queue(sprint, monkeypatch):
    manager, current, query = sprint
    history = current
    now = datetime.now(UTC)
    original = current.fetch
    stamp = now - timedelta(hours=3)

    async def fetch(key, *, reservation=None):
        unit, _ = await original(key, reservation=reservation)
        return unit, stamp

    current.fetch = fetch
    await collect(current)
    stamp = now - timedelta(hours=1)
    archive = manager.registry.get('archive.worker')
    writes = []

    def track(conn, cursor, statement, params, context, many):
        if 'yuanhang_limit_' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)

    event.listen(query.mysql.engine, 'before_cursor_execute', track)
    await history.execute(baseline_revision=await history.checkpoint_revision(), history_only=True, maintenance_scope='backfill')  # Shared trusted fingerprint: no SQL business writes.
    assert not writes
    await archive.fingerprints.invalidate(LimitDataset(current.pool).FINGERPRINT_NAMESPACE, SOURCE)
    await history.execute(baseline_revision=await history.checkpoint_revision(), history_only=True, maintenance_scope='backfill')  # Cold SQL confirms the newer unchanged version in this owner.
    assert not writes
    with query.mysql.engine.connect() as conn:
        versions = pool_versions(conn, query.namespace, current.pool)
    assert datetime.fromisoformat(versions['2026-07-15']) == now - timedelta(hours=1)
    await archive.fingerprints.invalidate(LimitDataset(current.pool).FINGERPRINT_NAMESPACE, SOURCE)
    unit, _ = await current.fetch('2026-07-15')
    unit['rows'][0]['name'] = 'late revision'
    stale = current.envelope(dict(page=0, batch_id='single-owner-stale'), unit, now - timedelta(hours=2))
    outcome = await archive._archive_data(stale, LimitDataset(current.pool).normalize(stale))
    assert outcome['written_count'] == 0 and not writes
    assert (await query.members('2026-07-15', current.pool))['rows'][0]['name'] == '样本'
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0
    assert (await current.ingest.checkpoint(current.job_key))['cursor']['phase'] == 'complete'
    assert (await history.ingest.checkpoint(history.job_key))['cursor']['phase'] == 'complete'
    await calendar(query, monkeypatch)
    query.collection_plan = LimitQuery.collection_plan.__get__(query)
    query.cache_proofs = AsyncMock(return_value={})
    assert not (await query.collection_plan(current.pool, scope='recent'))['units']
    assert not (await query.collection_plan(current.pool, scope='backfill'))['units']


async def test_recent_cache_reads_only_due_candidates_and_reuses_sql_coverage(sprint, monkeypatch):
    _, current, query = sprint
    await collect(current)
    await calendar(query, monkeypatch)
    query.collection_plan = LimitQuery.collection_plan.__get__(query)
    query.cache_proofs = AsyncMock(return_value={})
    assert not (await query.collection_plan(current.pool, scope='recent'))['units']
    query.cache_proofs.assert_not_awaited()


async def test_same_day_late_source_revision_is_refreshed_automatically(sprint, monkeypatch):
    manager, current, query = sprint
    original_fetch = current.fetch
    async def dated_fetch(key, **kwargs):
        unit, _ = await original_fetch(key, **kwargs)
        return unit, datetime(2026, 7, 15, 7, 30, tzinfo=UTC)
    current.fetch = dated_fetch
    current.http.request.return_value = httpx.Response(200, json=page([row('000001'), row('000917')]))
    await collect(current)
    assert (await query.audit_pool('2026-07-15', current.pool))['count'] == 2
    await calendar(query, monkeypatch)
    query.collection_plan = LimitQuery.collection_plan.__get__(query)
    query.cache_proofs = AsyncMock(return_value={})
    current.http.request.return_value = httpx.Response(200, json=page([row('000001')]))
    await collect(current)
    assert current.stats['requests'] == 0
    assert (await query.audit_pool('2026-07-15', current.pool))['count'] == 2
    from empire.core.time import CHINA
    from empire.features.yuanhang_limits import query as query_module
    from empire.features.yuanhang_limits.intraday import pool_maintenance
    from empire.features.yuanhang_limits.intraday_store import IntradayStore
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 15, 16, tzinfo=CHINA).astimezone(tz)
    monkeypatch.setattr(query_module, 'datetime', Clock)
    store = manager.registry.get('redis.store')
    current.live_store = IntradayStore(store)
    async def refreshed_fetch(key, **kwargs):
        unit, _ = await original_fetch(key, **kwargs)
        return unit, datetime(2026, 7, 15, 8, tzinfo=UTC)
    current.fetch = refreshed_fetch
    await pool_maintenance(current, Clock.now(CHINA), fresh=False,
                           baseline_revision=await current.checkpoint_revision())
    assert current.stats['requests'] == 1
    assert [r['unified_code'] for r in (await query.members('2026-07-15', current.pool))['rows']] == ['000001.SZ']
    assert (await query.audit_pool('2026-07-15', current.pool))['count'] == 1
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0
    assert await current.live_store.close_slot(current.pool) == '2026-07-15T16:00+08:00'
    await pool_maintenance(current, Clock.now(CHINA), fresh=False,
                           baseline_revision=await current.checkpoint_revision())
    assert current.stats['requests'] == 0
    # Losing only the volatile freshness marker forces one bounded reread.
    await store.client.hdel(current.live_store.keys(current.pool)[2], 'close_slot')
    writes = []
    def track(conn, cursor, statement, params, context, many):
        if 'yuanhang_limit_' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(query.mysql.engine, 'before_cursor_execute', track)
    await pool_maintenance(current, Clock.now(CHINA), fresh=False,
                           baseline_revision=await current.checkpoint_revision())
    assert current.stats['requests'] == 1 and not writes
    assert await store.client.xlen(store.stream) == 0
