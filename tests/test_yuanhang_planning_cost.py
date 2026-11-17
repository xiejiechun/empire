"""Bound work independently of decades of already confirmed history."""
from datetime import date, timedelta
from unittest.mock import AsyncMock

import pytest

from empire.features.yuanhang import plan_query
from empire.features.yuanhang.planning import PlanningCalendar
from empire.features.yuanhang.query import YuanhangDataPlugin
from empire.sources import yuanhang_ranges as ranges
from empire.sources.yuanhang_payload import CONTRACT

VERSION = '2026-10-23T08:00:00.000000+00:00'


def test_recent_64_old_stocks_only_materialize_640_dates(monkeypatch):
    codes = [f'{i:06}.SZ' for i in range(64)]
    heads = [dict(quote_year=y, native_market='USZA', last_date=date(y, 12, 31) if y < 2026
                  else date(2026, 10, 23), contract_version=CONTRACT) for y in range(2000, 2027)]
    unit = dict(price_ranges={str(y): [[f'{y}-01-01', f'{y}-12-31' if y < 2026 else '2026-10-23', VERSION]]
                              for y in range(2000, 2027)})
    monkeypatch.setattr(plan_query, 'read_plan_inputs', lambda *_: ({c: heads for c in codes}, {c: unit for c in codes}))
    monkeypatch.setattr(ranges, 'expand_versions', lambda *_: pytest.fail('daily expansion in planner'))
    monkeypatch.setattr(plan_query, 'contiguous_through', lambda *_: pytest.fail('old annual coverage in recent plan'))
    count = []
    original = plan_query.versions_on
    def selected(segments, year, days):
        count.extend(days)
        return original(segments, year, days)
    monkeypatch.setattr(plan_query, 'versions_on', selected)
    first, last = date(2026, 10, 1), date(2026, 10, 23)
    calendar = PlanningCalendar([(str(first + timedelta(days=i)), 1)
                                 for i in range((last-first).days + 1)], str(last))
    result = plan_query.read_plans(None, 'test', codes, str(last), scope='recent', calendar_cache={'calendar': calendar})
    assert {p['mode'] for p in result.values()} == {'skip'}
    assert len(count) == 640


@pytest.mark.parametrize('year', [2000, 2025, 2026])
def test_contiguous_ranges_match_daily_oracle_without_expansion(monkeypatch, year):
    first = date(year, 1, 1)
    for gap in (0, 31, 59, 365):
        segments = [[str(first), str(first + timedelta(days=gap)), VERSION]]
        if gap < 300:
            segments.append([str(first + timedelta(days=gap + 2)), f'{year}-12-31', VERSION])
        if date.fromisoformat(segments[0][1]).year != year:
            continue
        expected = segments[0][1]
        monkeypatch.setattr(ranges, 'expand_versions', lambda *_: pytest.fail('expanded dates'))
        assert ranges.contiguous_through(segments, year) == expected


def test_invalid_tail_is_checked_even_after_a_gap():
    with pytest.raises(ValueError, match='overlap'):
        ranges.contiguous_through([['2026-02-01', '2026-03-01', VERSION],
                                   ['2026-02-20', '2026-03-02', VERSION]], 2026)


async def test_backfill_stops_after_enough_candidates_and_later_round_reaches_tail(monkeypatch):
    codes = [f'{i:06}.SZ' for i in range(200)]
    completed, visited = set(), []
    def read(conn, ns, batch, through, **kwargs):
        visited.append(list(batch))
        return {c: dict(mode='skip' if c in completed else 'full') for c in batch}
    monkeypatch.setattr(plan_query, 'read_plans', read)
    query = YuanhangDataPlugin('test')
    query._read = AsyncMock(side_effect=lambda fn: fn(None))
    first = await query.daily_plans('test', codes, '2026-10-23', scope='backfill')
    assert list(first) == codes[:64] and len(visited) == 1
    completed.update(first)
    second = await query.daily_plans('test', codes, '2026-10-23', scope='backfill')
    assert [c for c, p in second.items() if p['mode'] != 'skip'] == codes[64:128]
    assert len(visited) == 3
