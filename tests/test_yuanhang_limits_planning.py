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
    assert result.days == tuple(reversed(DAYS[-8:]))


def test_one_gap_does_not_trigger_entire_history():
    result = plan(set(DAYS) - {DAYS[3]})
    assert result.days == (DAYS[3],)


def test_new_day_checks_only_ten_day_tail():
    result = plan(coverage=set(DAYS[:-1]), verified=dict.fromkeys(DAYS[:-1], DAYS[-2]))
    assert set(result.days) == set(DAYS[-10:])


def test_old_complete_history_is_not_periodically_downloaded():
    result = plan(verified=dict.fromkeys(DAYS, DAYS[0]), lookback=1)
    assert result.days == (DAYS[-1],)


def test_future_proofs_and_duplicate_calendar_fail():
    with pytest.raises(ValueError):
        plan(verified={DAYS[0]: '2026-08-01'})
    with pytest.raises(ValueError):
        plan_pool(DAYS + [DAYS[-1]], set(), {}, cutoff=DAYS[-1])


def test_recent_and_backfill_are_disjoint_without_periodic_audit():
    from datetime import date, timedelta
    days = [(date(1990, 12, 19) + timedelta(days=i)).isoformat() for i in range(8754)]
    verified = dict.fromkeys(days[:-1], days[-2])
    coverage = set(days[:-1])
    recent = plan_pool(days, coverage, verified, cutoff=days[-1], scope='recent')
    history = plan_pool(days, coverage, verified, cutoff=days[-1], scope='backfill')
    assert set(recent.days) == set(days[-10:])
    assert recent.remaining == 0
    assert history.missing == 0
    assert history.days == () and history.remaining == 0
    assert not (set(recent.days) & set(history.days))


def test_missing_old_date_belongs_only_to_backfill():
    coverage = set(DAYS) - {DAYS[2]}
    assert plan(coverage, scope='recent').days == ()
    assert plan(coverage, scope='backfill').days == (DAYS[2],)
    assert plan(scope='recent').days == ()
    assert plan(scope='backfill').days == ()


def test_backfill_leaves_complete_history_and_rejects_unknown_scope():
    verified = dict.fromkeys(DAYS, DAYS[0])
    history = plan(verified=verified, scope='backfill')
    assert history.days == ()
    assert set(plan(verified=verified, scope='recent').days) == set(DAYS[-10:])
    with pytest.raises(ValueError, match='范围'):
        plan(scope='invalid')


async def test_recent_query_reads_ten_candidate_fingerprints_instead_of_8754():
    from datetime import date, timedelta
    from unittest.mock import AsyncMock

    from empire.features.yuanhang_limits.query import LimitQuery
    days = [(date(1990, 12, 19) + timedelta(days=i)).isoformat() for i in range(8754)]
    query = LimitQuery('test')
    heads = [dict(trade_date=date.fromisoformat(day), contract_version=1, content_sha256='a' * 64) for day in days]
    versions = dict.fromkeys(days, days[-2] + 'T00:00:00+00:00')
    query.read = AsyncMock(return_value=(days[-1], days, heads, versions))
    query.cache_proofs = AsyncMock(return_value={})
    result = await query.collection_plan('sprint_limit_up', scope='recent')
    assert set(result['units']) == set(days[-10:])
    assert result['remaining'] == 0 and result['pending'] == []
    query.cache_proofs.assert_awaited_once()
    assert len(query.cache_proofs.call_args.args[1]) == 10


def test_uninitialized_recent_does_not_include_old_missing_days():
    recent = plan(set(), {}, scope='recent')
    older = plan(set(), {}, scope='backfill', batch_limit=3)
    assert recent.days == tuple(reversed(DAYS[-10:]))
    assert recent.missing == 10 and recent.remaining == 0
    assert older.days == tuple(DAYS[:3]) and older.remaining == 7
    assert not set(recent.days) & set(older.days)
