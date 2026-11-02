"""One task finishes recent work before a separate evening history round."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.core.time import CHINA
from empire.features.yuanhang_limits.collector import LimitCollector
from empire.features.yuanhang_limits.contract import POOLS
from empire.features.yuanhang_limits.intraday import pool_maintenance


@pytest.mark.parametrize('clock,recent,history,fresh,expected', [
    ('15:30', False, False, False, 'recent'),
    ('18:30', False, False, False, 'recent'),
    ('18:29', True, False, False, None),
    ('18:30', True, False, False, 'history'),
    ('19:00', True, True, False, None),
    ('19:00', True, True, True, 'recent'),
])
@pytest.mark.parametrize('pool', POOLS)
async def test_single_run_scope_and_completion_markers(pool, clock, recent, history, fresh, expected):
    day = '2026-11-02'
    c = LimitCollector(pool, scope='recent', intraday=True)
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(return_value=dict(revision=0, cursor={})))
    async def marked(pool, *, history=False):
        return day if (historical_done if history else recent) else None
    historical_done = history
    c.live_store = SimpleNamespace(maintenance_day=AsyncMock(side_effect=marked), mark_maintenance=AsyncMock())
    c.query = SimpleNamespace(collection_plan=AsyncMock(return_value=dict(cutoff=day, units=[])))
    c._execute = AsyncMock(return_value=dict(cutoff=day, phase='complete'))
    await pool_maintenance(c, datetime.fromisoformat(day + 'T' + clock).replace(tzinfo=CHINA),
                             fresh=fresh, baseline_revision=0)
    if expected is None:
        c._execute.assert_not_awaited()
        c.live_store.mark_maintenance.assert_not_awaited()
        assert c.stats['requests'] == 0
    else:
        c._execute.assert_awaited_once_with(fresh=fresh, baseline_revision=0, history_only=True, scope=expected)
        c.query.collection_plan.assert_awaited_once_with(c.pool, scope=expected)
        c.live_store.mark_maintenance.assert_awaited_once_with(c.pool, day, history=expected == 'history')


@pytest.mark.parametrize('pool', POOLS)
async def test_interrupted_history_resumes_its_scope_without_marking_new_day(pool):
    c = LimitCollector(pool, scope='recent', intraday=True)
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(return_value=dict(revision=4,
        cursor=dict(phase='fetch', scope='history', cutoff='2026-10-30'))))
    c.live_store = SimpleNamespace(maintenance_day=AsyncMock(), mark_maintenance=AsyncMock())
    c.query = SimpleNamespace(collection_plan=AsyncMock(return_value=dict(cutoff='2026-11-02', units=['2026-11-02'])))
    c._execute = AsyncMock(return_value=dict(cutoff='2026-10-30', phase='complete'))
    await pool_maintenance(c, datetime(2026, 11, 2, 16, tzinfo=CHINA), fresh=False, baseline_revision=4)
    assert c._execute.call_args.kwargs['scope'] == 'history'
    c.live_store.mark_maintenance.assert_not_awaited()


@pytest.mark.parametrize('pool', POOLS)
async def test_failure_never_marks_either_scope_complete(pool):
    c = LimitCollector(pool, scope='recent', intraday=True)
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(return_value=dict(revision=0, cursor={})))
    c.live_store = SimpleNamespace(maintenance_day=AsyncMock(return_value=None), mark_maintenance=AsyncMock())
    c._execute = AsyncMock(side_effect=ValueError('incomplete source'))
    with pytest.raises(ValueError, match='incomplete source'):
        await pool_maintenance(c, datetime(2026, 11, 2, 19, tzinfo=CHINA), fresh=False, baseline_revision=0)
    c.live_store.mark_maintenance.assert_not_awaited()


@pytest.mark.parametrize('scope', ['all', 'history'])
async def test_durable_scope_survives_failure_and_default_scope_on_resume(scope):
    from tests.test_yuanhang_limits_collector import setup_collector
    c, state, events, _ = setup_collector(['2026-07-14', '2026-07-15'])
    c.scope = 'recent'
    original = c.fetch.side_effect
    async def fail(day, **kwargs):
        if day == '2026-07-15':
            raise ValueError('missing historical page')
        return await original(day, **kwargs)
    c.fetch.side_effect = fail
    with pytest.raises(ValueError):
        await c.execute(maintenance_scope=scope)
    assert state['cursor']['scope'] == scope and len(events) == 1
    c.fetch.side_effect = original
    await c.execute(baseline_revision=state['revision'])
    assert state['cursor']['scope'] == scope and len(events) == 2
    assert c.stats['unit_name'] == ('个历史日期池' if scope == 'history' else '个完整单元')
