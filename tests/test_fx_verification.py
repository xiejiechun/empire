"""Daily protocol boundaries must not depend on unrelated realhead fields."""
import copy
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.contracts.collector import CollectionSourceGap
from empire.core.time import CHINA
from empire.features.fx.source import recent
from empire.features.fx.verification import agrees, reconcile, verified_snapshot
from tests.test_fx import CODE, collector, source, today_source

NOW = datetime(2026, 11, 10, 9, tzinfo=CHINA)
OLD = ['2026-11-09', '6.6703', '6.67434', '6.66984', '6.67131']
CLOSED = ['2026-11-09', '6.6703', '6.67434', '6.66925', '6.66945']
CURRENT = ['2026-11-10', '6.67014', '6.6738', '6.66488', '6.67291']


def snapshot(rows):
    return recent(source(rows=rows, start='20261109', year={'2026': len(rows)},
                         total=str(len(rows))), CODE, NOW)


async def test_missing_current_reconciles_once_and_excludes_native_day():
    initial = snapshot([CLOSED])
    initial['source_years']['2026'] = initial['years']['2026'] = 2
    c = SimpleNamespace(stats={}, fetch=AsyncMock(side_effect=[(initial, NOW), CURRENT, [CLOSED]]))
    result, observed, verified = await verified_snapshot(c, CODE)
    assert result['rows'] == [CLOSED] and result['years'] == {'2026': 1}
    assert result['source_tail'] == [CLOSED, CURRENT]
    assert observed == NOW and verified == {2026: [CLOSED]}
    assert c.fetch.await_count == 3


async def test_matching_recent_uses_only_two_daily_responses():
    initial = snapshot([CLOSED, CURRENT])
    c = SimpleNamespace(stats={}, fetch=AsyncMock(side_effect=[(initial, NOW), CURRENT]))
    result, _, verified = await verified_snapshot(c, CODE)
    assert result['rows'] == [CLOSED] and verified == {} and c.fetch.await_count == 2
    assert c.fetch.await_args_list[1].args == (CODE, 'today')


def test_annual_cannot_choose_a_different_closed_price_over_recent():
    older = ['2026-11-06', '6.6', '6.8', '6.5', '6.7']
    initial = dict(start='2016-01-03', end=CLOSED[0], years={'2026': 2},
        rows=[older, CLOSED], source_tail=[older, CLOSED], source_years={'2026': 3})
    for candidate in ([[*older[:4], '6.65'], CLOSED, CURRENT], [older, OLD, CURRENT]):
        with pytest.raises(ValueError, match='内容不一致'):
            reconcile(initial, {2026: candidate}, NOW, CURRENT)


def test_same_count_changed_date_set_is_not_a_valid_annual_candidate():
    older = ['2026-11-06', '6.6', '6.8', '6.5', '6.7']
    initial = dict(start='2016-01-03', end=CLOSED[0], years={'2026': 2},
        rows=[older, CLOSED], source_tail=[older, CLOSED], source_years={'2026': 3})
    with pytest.raises(ValueError, match='日期集合不一致'):
        reconcile(initial, {2026: [['2026-11-05', *older[1:]], CLOSED, CURRENT]}, NOW, CURRENT)


@pytest.mark.parametrize('candidate', [[OLD, CURRENT], [CURRENT]])
async def test_unresolved_content_or_incomplete_year_does_not_retry(candidate):
    initial = snapshot([CLOSED])
    initial['source_years']['2026'] = 2
    c = SimpleNamespace(stats={}, records=SimpleNamespace(add_error=AsyncMock()), project_id='ths-fx-daily',
        fetch=AsyncMock(side_effect=[(initial, NOW), CURRENT, candidate]))
    with pytest.raises(ValueError, match='不一致|不完整'):
        await verified_snapshot(c, CODE)
    assert c.fetch.await_count == 3


def test_native_day_identity_and_open_are_required_and_closed_day_checks_all_prices():
    initial = snapshot([CLOSED, CURRENT])
    assert agrees(initial, CURRENT, NOW)
    assert not agrees(initial, ['2026-11-09', *CURRENT[1:]], NOW)
    assert not agrees(initial, [CURRENT[0], '6.6', *CURRENT[2:]], NOW)
    assert agrees(snapshot([CLOSED]), CLOSED, NOW)
    assert not agrees(snapshot([CLOSED]), OLD, NOW)


async def test_year_rollover_is_bounded_to_two_complete_source_years():
    observed = datetime(2027, 1, 1, 9, tzinfo=CHINA)
    previous = ['2026-12-31', '6.7', '6.8', '6.6', '6.75']
    today = ['2027-01-01', '6.76', '6.8', '6.7', '6.78']
    initial = dict(start=previous[0], end=previous[0], years={'2026': 1},
        rows=[previous], source_tail=[previous], source_years={'2026': 1})
    c = SimpleNamespace(stats={}, fetch=AsyncMock(side_effect=[(initial, observed), today, [previous], [today]]))
    result, _, verified = await verified_snapshot(c, CODE)
    assert result['rows'] == [previous] and verified == {2026: [previous]}
    assert c.fetch.await_count == 4


async def test_conflict_is_rejected_before_any_enqueue_or_checkpoint_advance():
    c = collector()
    initial = snapshot([CLOSED])
    initial['source_years']['2026'] = 2
    c.fetch = AsyncMock(side_effect=[(initial, NOW), CURRENT, [OLD, CURRENT]])
    before = copy.deepcopy(c.ingest.state)
    with pytest.raises(CollectionSourceGap, match='USDCNH'):
        await c.execute()
    assert c.ingest.events == [] and c.ingest.state == before
    c.confirmation.page_status.assert_not_awaited()


async def test_reconciled_year_is_reused_during_initialization(monkeypatch):
    monkeypatch.setattr('empire.features.fx.transport.datetime', SimpleNamespace(now=lambda _: NOW))
    c = collector()
    def request(method, url, **kwargs):
        if '/today.js' in url:
            body = today_source(CURRENT)
        elif '/last.js' in url:
            body = source(rows=[CLOSED], start='20261109', year={'2026': 2}, total='2')
        else:
            body = source(2026, [CLOSED, CURRENT])
        return httpx.Response(200, content=body.encode())
    c.http.request.side_effect = request
    result = await c.execute()
    assert result['phase'] == 'complete' and c.http.request.await_count == 3
    assert c.ingest.events[0].raw_payload['rows'] == [CLOSED]
