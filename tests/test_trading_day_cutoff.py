from contextlib import nullcontext
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest

from empire.core.time import CHINA
from empire.plugins.data.trading_day_cutoff import coverage_as_of, last_closed_trade_day


def calendar(start='2026-09-30', end='2026-10-08', trade_days=('2026-09-30', '2026-10-08')):
    day, last = date.fromisoformat(start), date.fromisoformat(end)
    rows = []
    while day <= last:
        rows.append(dict(trade_date=day, is_trade=int(day.isoformat() in trade_days)))
        day += timedelta(days=1)
    return rows


@pytest.mark.parametrize('hour,minute', [(0, 1), (9, 15), (9, 30), (11, 30), (13, 0), (15, 0), (15, 29)])
def test_opening_auction_intraday_and_after_hours_do_not_require_unfinished_day(hour, minute):
    target, note = last_closed_trade_day(calendar(), datetime(2026, 10, 8, hour, minute, tzinfo=CHINA))
    assert target.date() == date(2026, 9, 30)
    assert '尚未结束' in note


@pytest.mark.parametrize('day', [1, 2, 3, 4, 5, 6, 7])
def test_long_holiday_does_not_expire_verified_last_trading_day(day):
    now = datetime(2026, 10, day, 16, tzinfo=CHINA)
    target, note = last_closed_trade_day(calendar(), now)
    assert target.date() == date(2026, 9, 30)
    assert '休市日' in note
    status, _ = coverage_as_of(dict(confirmed_at='2026-10-01T07:20:46+08:00'), now, target)
    assert status == 'pass'


def test_end_of_trading_day_requires_today_and_post_close_confirmation():
    now = datetime(2026, 10, 8, 15, 30, tzinfo=CHINA)
    target, _ = last_closed_trade_day(calendar(), now)
    assert target == now
    assert coverage_as_of(dict(confirmed_at='2026-10-08T10:00:00+08:00'), now, target)[0] == 'fail'
    assert coverage_as_of(dict(confirmed_at=now.isoformat()), now, target)[0] == 'pass'


def test_missing_or_invalid_calendar_is_unknown_not_assumed_holiday():
    now = datetime(2026, 10, 2, 16, tzinfo=CHINA)
    for rows in (calendar(end='2026-10-01'), calendar()[1:],
                 [dict(trade_date=now.date(), is_trade=2)]):
        assert last_closed_trade_day(rows, now)[0] is None
    rows = [r for r in calendar() if r['trade_date'] != date(2026, 10, 1)]
    assert last_closed_trade_day(rows, now)[0] is None


def test_calendar_flag_overrides_weekday_assumptions():
    # Source can declare Saturday trading or weekday closure; never generate flags.
    now = datetime(2026, 10, 3, 16, tzinfo=CHINA)
    rows = calendar(end='2026-10-03', trade_days=('2026-10-03',))
    assert last_closed_trade_day(rows, now)[0].date() == now.date()


@pytest.mark.parametrize('stamp', ['2026-10-02', 'bad', '2026-10-04T00:00:00+08:00'])
def test_untrusted_confirmation_does_not_pass(stamp):
    now = datetime(2026, 10, 2, 16, tzinfo=CHINA)
    target, _ = last_closed_trade_day(calendar(), now)
    assert coverage_as_of(dict(confirmed_at=stamp), now, target)[0] == 'fail'


@pytest.mark.parametrize('through,calendar_known,expected', [
    ('2026-10-01', True, 'pass'), ('2026-09-29', True, 'fail'), ('2026-10-01', False, 'unknown')])
def test_suspension_checker_preserves_real_gaps_and_missing_calendar(monkeypatch, through, calendar_known, expected):
    from empire.plugins.data import preparation_checks as module
    now = datetime(2026, 10, 2, 16, tzinfo=CHINA)
    target, note = last_closed_trade_day(calendar(), now)
    state = dict(collection_integrity_version=2, coverage=dict(
        through=through, confirmed_at='2026-10-01T07:20:00+08:00'))
    state['coverage']['from'] = '2004-12-27'
    row = dict(total=1, identities=1, earliest=None, latest=None, bad=0, markets=2, missing_dates=0)
    conn = SimpleNamespace(execute=lambda *args, **kwargs: SimpleNamespace(
        mappings=lambda: SimpleNamespace(one=lambda: row)))
    plugin = SimpleNamespace(source='tdx', namespace='test', project_id='tdx-suspensions',
        mysql=SimpleNamespace(read_engine=SimpleNamespace(connect=lambda: nullcontext(conn))))
    monkeypatch.setattr(module, 'datetime', SimpleNamespace(now=lambda tz: now))
    monkeypatch.setattr(module, 'read_state', lambda *args: state)
    monkeypatch.setattr(module, 'read_trade_day_cutoff', lambda *args: (target if calendar_known else None, note))
    checks = {c.criterion:c for c in module.check_suspensions(plugin)}
    assert checks['coverage'].status == expected
    assert checks['fields'].status == checks['keys'].status == checks['quality'].status == 'pass'
