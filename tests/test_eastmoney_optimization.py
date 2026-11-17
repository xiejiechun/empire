from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.core.time import CHINA
from empire.features.graymarket import intraday
from tests.test_graymarket_lifecycle import collector


@pytest.fixture
def planned(monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 2, 16, 0, tzinfo=CHINA)
    monkeypatch.setattr(intraday, 'datetime', Clock)
    c, state, published = collector()
    c.query.trading_dates.return_value = ['2026-11-02']
    c.query.maintenance_plan = AsyncMock(return_value=['2026-10-29', '2026-10-30', '2026-11-02'])
    marks = {}
    async def mark(slot):
        marks['slot'] = slot
    c.live_store = SimpleNamespace(maintenance=AsyncMock(side_effect=lambda: marks.get('slot')),
                                   mark_maintenance=AsyncMock(side_effect=mark))
    return c, state, published, marks


async def test_same_plan_reused_no_discovery_or_second_sql(planned):
    c, state, published, marks = planned
    await intraday.dispatch(c, fresh=False, baseline_revision=0)
    assert c.http.request.call_count == 6
    assert all(call.kwargs['params']['date'] for call in c.http.request.call_args_list)
    c.query.trading_dates.assert_awaited_once_with('2026-11-02', '2026-11-02')
    c.query.covered.assert_not_called()
    c.query.maintenance_plan.assert_awaited_once_with('2026-11-02', recent=3)
    assert state['cursor']['maintenance_slot'] == marks['slot']
    assert len(published) == 3


@pytest.mark.parametrize('failure', ['archive', 'mark'])
async def test_resume_repairs_maintenance_without_refetch(planned, monkeypatch, failure):
    c, state, _, marks = planned
    if failure == 'archive':
        monkeypatch.setattr('empire.features.graymarket.collector.wait_for_archive',
                            AsyncMock(side_effect=RuntimeError('archive failed')))
    else:
        c.live_store.mark_maintenance.side_effect = RuntimeError('mark failed')
    with pytest.raises(RuntimeError):
        await intraday.dispatch(c, fresh=False, baseline_revision=0)
    requests = c.http.request.call_count
    monkeypatch.setattr('empire.features.graymarket.collector.wait_for_archive', AsyncMock())
    async def mark(slot):
        marks['slot'] = slot
    c.live_store.mark_maintenance.side_effect = mark
    c.query.maintenance_plan.return_value = []
    await intraday.dispatch(c, fresh=False, baseline_revision=state['revision'])
    await intraday.dispatch(c, fresh=False, baseline_revision=state['revision'])
    assert marks['slot'] == '2026-11-02T16:00+08:00'
    assert c.http.request.call_count == requests


async def test_backfill_does_not_mark_close_or_discover_latest(planned):
    c, state, _, marks = planned
    marks['slot'] = '2026-11-02T16:00+08:00'
    c.query.maintenance_plan.return_value = ['2026-10-29', '2026-10-30']
    await intraday.dispatch(c, fresh=False, baseline_revision=0)
    assert c.http.request.call_count == 4
    assert state['cursor']['maintenance_slot'] is None
    c.live_store.mark_maintenance.assert_not_called()


async def test_unchanged_snapshot_skips_packing(monkeypatch):
    from empire.features.graymarket import intraday_store
    redis = SimpleNamespace(prefix='test', client=SimpleNamespace(eval=AsyncMock(return_value=[0, 0])))
    monkeypatch.setattr(intraday_store, 'pack', lambda _: pytest.fail('unchanged content compressed'))
    now = datetime.now(CHINA)
    result = await intraday_store.IntradayStore(redis).save(now.date().isoformat(), [], now, now)
    assert result == dict(changed=False, stale=False, evicted=0)
    assert redis.client.eval.call_args.args[7] == ''
