"""Audit shared archive branching without writing to Redis or any MySQL database."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.contracts.archive_version import ArchiveVersion
from empire.plugins.pipeline.archive import ArchivePlugin
from empire.plugins.pipeline.fingerprints import digest


def worker(plan, cached):
    w = ArchivePlugin({})
    w.catalog = SimpleNamespace(
        fingerprint_plan=lambda *_: ("audit", plan),
        fingerprint_version=lambda _: ArchiveVersion(("utc",), observed_index=0),
        fingerprint_source=lambda _: "source",
        stale_outcome=lambda _: "complete",
        project_id=lambda _: "audit",
        fingerprint_subset=lambda envelope, data, ids: {**data, "pending": ids},
    )
    w.fingerprints = SimpleNamespace(get=AsyncMock(return_value=cached), put=AsyncMock())
    w.mysql = SimpleNamespace(
        archive=AsyncMock(
            return_value=[
                dict(status="complete", row_count=1, written_count=0, confirmed=list(plan))
            ]
        )
    )
    w.states = SimpleNamespace(writer=lambda *_: object())
    w.metrics.reset(["audit"])
    return w


def version(offset=0):
    return [
        (datetime.now(UTC) - timedelta(minutes=10) + timedelta(seconds=offset)).isoformat(
            timespec="microseconds"
        )
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("older", [False, True])
async def test_trusted_equal_or_older_proof_skips_mysql_entirely(older):
    v = version()
    prior = version(5) if older else v
    w = worker(
        {"one": ({"amount": "1"}, v)}, {"one": dict(hash=digest({"amount": "1"}), version=prior)}
    )
    result = await w._archive_data(object(), {"row_count": 1})
    assert result["written_count"] == 0
    w.mysql.archive.assert_not_awaited()


@pytest.mark.asyncio
async def test_only_changed_keys_reach_sql():
    v = version()
    plan = {"hit": ({"amount": "1"}, v), "miss": ({"amount": "2"}, v)}
    w = worker(plan, {"hit": dict(hash=digest({"amount": "1"}), version=v)})
    await w._archive_data(object(), {"row_count": 2})
    assert w.mysql.archive.call_args.args[0][0]["normalized"]["pending"] == {"miss"}


@pytest.mark.asyncio
@pytest.mark.parametrize("plan", [{}, {"one": ({"amount": "1"}, version())}])
async def test_missing_or_empty_proof_does_not_pretend_sql_free(plan):
    w = worker(plan, {})
    await w._archive_data(object(), {"row_count": 1})
    w.mysql.archive.assert_awaited_once()


@pytest.mark.asyncio
async def test_failed_sql_never_publishes_cache():
    w = worker({"one": ({"amount": "1"}, version())}, {})
    w.mysql.archive.side_effect = RuntimeError("test SQL failure")
    with pytest.raises(RuntimeError, match="test SQL failure"):
        await w._archive_data(object(), {"row_count": 1})
    w.fingerprints.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_confirmation_failure_is_not_silently_successful():
    v = version()
    w = worker(
        {"one": ({"amount": "1"}, v)}, {"one": dict(hash=digest({"amount": "1"}), version=v)}
    )
    w.fingerprints.put.side_effect = RuntimeError("test Redis failure")
    with pytest.raises(RuntimeError, match="test Redis failure"):
        await w._archive_data(object(), {"row_count": 1})
    w.mysql.archive.assert_not_awaited()


@pytest.mark.asyncio
async def test_metrics_distinguish_equal_stale_missing_changed_and_sql():
    v = version()
    newer = version(5)
    plan = {k: ({"amount": "1"}, v) for k in ("equal", "stale", "changed", "missing")}
    cached = {
        "equal": dict(hash=digest({"amount": "1"}), version=v),
        "stale": dict(hash=digest({"amount": "9"}), version=newer),
        "changed": dict(hash=digest({"amount": "2"}), version=v),
    }
    w = worker(plan, cached)
    w.mysql.archive.return_value = [
        dict(status="complete", row_count=2, written_count=1, confirmed=["changed", "missing"])
    ]
    await w._archive_data(object(), {"row_count": 4})
    actual = w.metrics.snapshot("audit")
    assert {k: v for k, v in actual.items() if k not in {"since", "timings"}} == dict(
        checked=4,
        equal=1,
        stale=1,
        changed=1,
        missing=1,
        sql_attempts=1,
        sql_successes=1,
        written=1,
        acknowledged=0,
        deleted=0,
    )


@pytest.mark.asyncio
async def test_sql_failure_counts_attempt_but_not_success_or_write():
    w = worker({"one": ({"amount": "1"}, version())}, {})
    w.mysql.archive.side_effect = RuntimeError("failure")
    with pytest.raises(RuntimeError):
        await w._archive_data(object(), {"row_count": 1})
    assert w.metrics.snapshot("audit")["sql_attempts"] == 1
    assert w.metrics.snapshot("audit")["sql_successes"] == 0
    assert w.metrics.snapshot("audit")["written"] == 0


def test_metrics_unknown_projects_do_not_allocate_state():
    from empire.plugins.pipeline.archive_metrics import ArchiveMetrics

    m = ArchiveMetrics()
    m.reset(["known"])
    for n in range(1000):
        m.add(str(n), checked=1)
    assert set(m.projects) == {"known"}
    view = m.snapshot("known")
    view["checked"] = 999
    assert m.snapshot("known")["checked"] == 0
