from datetime import date, timedelta

import pytest

from empire.features.yuanhang.planning import plan_daily

# Explicit fake calendar for unit tests, not a production weekend inference.
DAYS = [(str(date(2026,1,1) + timedelta(days=i)), 1) for i in range(100)]
BASE = dict(code='000001.SZ', through='2026-04-10', calendar=DAYS,
            coverage='2026-04-09', full_checked='2026-04-09', latest_quote='2026-04-09')


def test_new_security_only_full_existing_skip_has_zero_request():
    assert plan_daily(**{**BASE, 'coverage': None}).reason == 'missing_initial_coverage'
    plan = plan_daily(**{**BASE, 'coverage': BASE['through'], 'full_checked': BASE['through']})
    assert plan.requests == 0 and plan.mode == 'skip'


def test_tail_keeps_ten_days_and_explicit_all_scope_keeps_gaps():
    plan = plan_daily(**BASE)
    assert plan.start == '2026-04-01' and plan.requests == 1
    plan = plan_daily(**{**BASE, 'coverage': '2026-03-20', 'latest_quote': '2026-03-20'})
    assert plan.start == '2026-03-20' and plan.end == '2026-04-10'


def test_suspended_security_anchors_last_real_quote():
    plan = plan_daily(**{**BASE, 'latest_quote': '2026-02-01'})
    assert plan.start == '2026-02-01'


def test_gap_and_tail_coalesce_into_one_request_and_unknown_anchor_is_explicit():
    plan = plan_daily(**{**BASE, 'gaps': [('2026-02-01', '2026-02-03')]})
    assert plan.start == '2026-02-01' and plan.requests == 1
    assert plan_daily(**{**BASE, 'latest_quote': None}).reason == 'missing_nonempty_anchor'


def test_old_full_check_never_triggers_periodic_full_download():
    plan = plan_daily(**{**BASE, 'full_checked': '2026-01-01'})
    assert plan.mode == 'range' and plan.start == '2026-04-01' and plan.requests == 1
    plan = plan_daily(**{**BASE, 'full_checked': BASE['through'], 'coverage': BASE['through']})
    assert plan.requests == 0


@pytest.mark.parametrize('changes', [
    {'calendar': DAYS[:4] + DAYS[5:]}, {'coverage': '2026-04-11'},
    {'lookback': 0}, {'scope': 'invalid'}, {'gaps': [('2026-03-01', '2026-02-01')]},
])
def test_invalid_or_incomplete_evidence_fails(changes):
    with pytest.raises(ValueError):
        plan_daily(**{**BASE, **changes})


def test_recent_excludes_known_old_gaps_and_backfill_preserves_them():
    args = {**BASE, 'gaps': [('2026-02-01', '2026-02-03')]}
    assert plan_daily(**args, scope='recent').start == '2026-04-01'
    assert plan_daily(**args, scope='backfill').start == '2026-02-01'
