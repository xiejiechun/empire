import pytest

from empire.features.yuanhang_limits.planning import plan_pool

DAYS = [f'2026-07-{i:02}' for i in range(1, 21)]  # synthetic source-declared trading calendar


def plan(coverage=None, verified=None, **kwargs):
    return plan_pool(DAYS, set(DAYS) if coverage is None else coverage,
                     dict.fromkeys(DAYS, DAYS[-1]) if verified is None else verified,
                     cutoff=DAYS[-1], **kwargs)


def test_initialized_same_cutoff_and_redis_loss_have_zero_work():
    assert plan().days == ()
    # There is deliberately no Redis cursor input to this SQL-based recovery.
    assert plan().missing == 0


def test_initialization_recent_priority_bounded_and_older_progress():
    result = plan(set(), {}, batch_limit=8)
    assert len(result.days) == 8 and result.missing == 20 and result.remaining == 12
    assert result.days[:4] == tuple(reversed(DAYS[-4:]))
    assert result.days[4:] == tuple(DAYS[:4])


def test_one_gap_does_not_trigger_entire_history():
    result = plan(set(DAYS) - {DAYS[3]})
    assert result.days == (DAYS[3],)


def test_new_day_adds_tail_and_only_due_historical_bucket():
    result = plan(coverage=set(DAYS[:-1]), verified=dict.fromkeys(DAYS[:-1], DAYS[-2]))
    assert set(result.days) == set(DAYS[-5:])


def test_missed_audits_are_caught_after_downtime():
    result = plan(verified=dict.fromkeys(DAYS, DAYS[0]), lookback=1, audit_period=5)
    assert set(result.days) == set(DAYS)


def test_future_proofs_and_duplicate_calendar_fail():
    with pytest.raises(ValueError):
        plan(verified={DAYS[0]: '2026-08-01'})
    with pytest.raises(ValueError):
        plan_pool(DAYS + [DAYS[-1]], set(), {}, cutoff=DAYS[-1])
