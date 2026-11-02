"""Post-close bounds, failures and durable recovery without historical requests."""
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.core.time import CHINA
from empire.features.yuanhang_limits.close_refresh import refresh_slot, today_plan
from empire.features.yuanhang_limits.contract import POOLS
from empire.features.yuanhang_limits.intraday import pool_maintenance
from tests.test_yuanhang_limits_collector import setup_collector


@pytest.mark.parametrize('clock,slot', [('15:30', None), ('15:59', None), ('16:00', '16:00'),
    ('16:29', '16:00'), ('16:30', '16:30'), ('20:59', '20:30'), ('21:00', '21:00'),
    ('21:01', '21:00'), ('23:59', '21:00'), ('00:00', None)])
def test_window_boundaries(clock, slot):
    now = datetime.fromisoformat('2026-11-02T' + clock).replace(tzinfo=CHINA)
    assert refresh_slot(now) == ('2026-11-02T' + slot + '+08:00' if slot else None)


@pytest.mark.parametrize('trade', [True, False])
async def test_today_plan_is_bounded_and_closed_day_has_no_units(trade):
    now = datetime(2026, 11, 2, 16, tzinfo=CHINA)
    cutoff = now if trade else now.replace(day=1)
    query = SimpleNamespace(read=AsyncMock(return_value=(cutoff, '')))
    plan = await today_plan(query, now)
    assert plan['units'] == (['2026-11-02'] if trade else [])
    assert plan['remaining'] == 0 and plan['pending'] == []
    assert not (await today_plan(query, now, exclude=['2026-11-02']))['units']


@pytest.mark.parametrize('pool', POOLS)
async def test_due_window_uses_one_day_then_waits_and_recovers_marker_loss(pool):
    day = '2026-11-02'
    c, state, events, _ = setup_collector([day])
    c.pool = pool
    async def fetch(key, **kwargs):
        from tests.test_yuanhang_limits_intraday import unit
        value = unit(key)
        value['pool_type'] = pool
        return value, datetime(2026, 11, 2, 16, tzinfo=CHINA)
    c.fetch = AsyncMock(side_effect=fetch)
    c.confirmation.page_status = AsyncMock(return_value={'status': 'complete'})
    marker = None
    async def marked(*args):
        return marker
    async def mark(_, slot):
        nonlocal marker
        marker = slot
    c.live_store = SimpleNamespace(maintenance_day=AsyncMock(return_value=day),
        close_slot=AsyncMock(side_effect=marked), mark_close_slot=AsyncMock(side_effect=mark))
    c.query.collection_plan = AsyncMock(return_value=dict(units=[day], cutoff=day,
        remaining=0, pending=[], close_slot=day + 'T16:00+08:00'))
    async def planning(*args, scope='all', **kwargs):
        result = dict(c.query.collection_plan.return_value)
        if scope != 'today':
            result['units'] = []
        return result
    c.query.collection_plan.side_effect = planning
    now = datetime(2026, 11, 2, 16, tzinfo=CHINA)
    await pool_maintenance(c, now, fresh=False, baseline_revision=state['revision'])
    assert len(events) == 1 and marker == day + 'T16:00+08:00'
    assert state['cursor']['scope'] == 'today'
    c.query.collection_plan.assert_any_await(pool, force=False, scope='today')
    await pool_maintenance(c, now.replace(minute=29), fresh=False, baseline_revision=state['revision'])
    assert len(events) == 1 and c.stats['requests'] == 0
    # Crash after completion checkpoint, before marker: same invocation repairs
    # the marker without downloading/queuing again.
    marker = None
    await pool_maintenance(c, now, fresh=False, baseline_revision=state['revision'] - 1)
    assert len(events) == 1 and marker is not None
    # Process/Redis lost marker: next invocation rechecks only today's one unit.
    marker = None
    await pool_maintenance(c, now, fresh=False, baseline_revision=state['revision'])
    assert len(events) == 2
    for hour, minute, expected in [(16, 30, 3), (20, 59, 4), (21, 0, 5), (23, 59, 5)]:
        stamp = now.replace(hour=hour, minute=minute)
        c.query.collection_plan.return_value['close_slot'] = refresh_slot(stamp)
        await pool_maintenance(c, stamp, fresh=False, baseline_revision=state['revision'])
        assert len(events) == expected  # No replay of missed half-hour windows.
    # A new day never trusts yesterday's final marker.
    c.live_store.maintenance_day.return_value = '2026-11-03'
    c.query.collection_plan.return_value.update(units=['2026-11-03'], cutoff='2026-11-03',
                                               close_slot='2026-11-03T16:00+08:00')
    await pool_maintenance(c, now.replace(day=3), fresh=False, baseline_revision=state['revision'])
    assert len(events) == 6 and marker == '2026-11-03T16:00+08:00'


async def test_today_failure_never_marks_success_and_resumes_original_window():
    day = '2026-11-02'
    c, state, _, _ = setup_collector([day])
    c.live_store = SimpleNamespace(maintenance_day=AsyncMock(return_value=day),
        close_slot=AsyncMock(return_value=None), mark_close_slot=AsyncMock())
    c.query.collection_plan = AsyncMock(return_value=dict(units=[day], cutoff=day,
        remaining=0, pending=[], close_slot=day + 'T20:30+08:00'))
    async def planning(*args, scope='all', **kwargs):
        result = dict(c.query.collection_plan.return_value)
        if scope != 'today':
            result['units'] = []
        return result
    c.query.collection_plan.side_effect = planning
    c.confirmation.page_status = AsyncMock(side_effect=RuntimeError('archive unavailable'))
    with pytest.raises(RuntimeError):
        await pool_maintenance(c, datetime(2026, 11, 2, 20, 30, tzinfo=CHINA), fresh=False, baseline_revision=0)
    c.live_store.mark_close_slot.assert_not_awaited()
    assert state['cursor']['phase'] == 'awaiting_archive'
    c.confirmation.page_status = AsyncMock(return_value={'status': 'complete'})
    await pool_maintenance(c, datetime(2026, 11, 2, 21, tzinfo=CHINA), fresh=False, baseline_revision=state['revision'])
    c.live_store.mark_close_slot.assert_awaited_once_with(c.pool, day + 'T20:30+08:00')
