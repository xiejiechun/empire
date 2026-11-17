import os
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.graymarket.intraday import collect_live, session_phase
from empire.features.graymarket.intraday_store import IntradayStore
from empire.plugins.infra.redis_store import create_client
from tests.test_graymarket import DayAssembly, parsed, response
from tests.test_graymarket_lifecycle import collector


@pytest.mark.parametrize("clock,trade,expected", [
    ("09:24", 1, "idle"), ("09:25", 1, "live"), ("11:30", 1, "live"),
    ("11:31", 1, "idle"), ("13:00", 1, "live"), ("15:05", 1, "live"),
    ("15:06", 1, "idle"), ("15:29", 1, "idle"), ("15:30", 1, "daily"),
    ("10:00", 0, "idle"), ("18:00", 0, "daily"),
])
def test_clock(clock, trade, expected):
    assert session_phase(datetime.fromisoformat("2026-11-03T" + clock).replace(tzinfo=CHINA), trade) == expected


def test_missing_calendar():
    with pytest.raises(ValueError):
        session_phase(datetime.now(CHINA), None)


@pytest.mark.parametrize("clock,accepted", [("10:00", False), ("15:29", False), ("15:30", True)])
def test_dataset_refuses_live_archive(clock, accepted):
    from empire.contracts.data import make_envelope
    from empire.features.graymarket.codec import pack
    from empire.features.graymarket.contract import DATASET, JOB
    from empire.features.graymarket.dataset import GraymarketDataset
    rows = DayAssembly(parsed(response(total=2))).finish()
    envelope = make_envelope(source="eastmoney", dataset=DATASET, job_key=JOB,
        business_key="2026-11-02", batch_id="test", run_id="test", schema_version=1,
        payload=dict(page=1, date="2026-11-02", source_latest="2026-11-02", rows=pack(rows)))
    envelope = envelope.model_copy(update=dict(observed_at=datetime.fromisoformat("2026-11-02T" + clock).replace(tzinfo=CHINA)))
    if accepted:
        assert GraymarketDataset().normalize(envelope)["row_count"] == 2
    else:
        with pytest.raises(ValueError, match="不得进入MySQL"):
            GraymarketDataset().normalize(envelope)


async def test_close_priority_then_bounded_backfill_and_no_work(monkeypatch):
    from empire.features.graymarket import intraday
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 3, 16, 0, tzinfo=CHINA)
    monkeypatch.setattr(intraday, "datetime", Clock)
    c, _, _ = collector()
    days = [f"2026-10-{d:02}" for d in range(12, 22)] + ["2026-11-02", "2026-11-03"]
    c.query.trading_dates.side_effect = lambda first, last: [days[-1]] if first == last else days
    c.query.maintenance_plan = AsyncMock(side_effect=lambda last, recent=0:
        days[-recent:] if recent else [d for d in days if d not in c.query.covered.return_value][:5])
    c._execute = AsyncMock(return_value=dict(phase="complete"))
    c.live_store = SimpleNamespace(maintenance=AsyncMock(return_value=None), mark_maintenance=AsyncMock())
    await intraday.dispatch(c, fresh=False, baseline_revision=0)
    assert c._execute.call_args.kwargs["sample_dates"] == days[-3:]
    c.live_store.maintenance.return_value = "2026-11-03T16:00+08:00"
    await intraday.dispatch(c, fresh=False, baseline_revision=0)
    assert c._execute.call_args.kwargs["sample_dates"] == days[:5]
    c.query.covered.return_value = set(days)
    c._execute.reset_mock()
    assert (await intraday.dispatch(c, fresh=False, baseline_revision=0))["storage"] == "none"
    c._execute.assert_not_called()
    c.http.request.assert_not_called()


async def test_live_does_not_publish_archive_or_advance_checkpoint():
    c, state, published = collector()
    c.live_store = SimpleNamespace(save=AsyncMock(return_value=dict(changed=True, stale=False, evicted=0)))
    async def publish(project, callback):
        return await callback()
    c.ingest.publish_volatile = AsyncMock(side_effect=publish)
    result = await collect_live(c, datetime.now(CHINA))
    assert result["storage"] == "redis_only" and result["queued_messages"] == 0
    assert not published and state == dict(revision=0, cursor={})
    assert c.http.request.call_count == 2 and c.http.buffer_budget.used == 0


async def test_rejected_volatile_publication_preserves_daily_state():
    c, state, published = collector()
    c.live_store = SimpleNamespace(save=AsyncMock())
    c.ingest.publish_volatile = AsyncMock(side_effect=RuntimeError("isolated"))
    with pytest.raises(RuntimeError, match="isolated"):
        await collect_live(c, datetime.now(CHINA))
    c.live_store.save.assert_not_called()
    assert not published and state["revision"] == 0


async def test_live_to_daily_and_idle_clear_storage_and_previous_metrics():
    from empire.features.graymarket.intraday import idle
    c, _, published = collector()
    c.live_store = SimpleNamespace(save=AsyncMock(return_value=dict(changed=True, stale=False, evicted=0)))
    async def publish(project, callback):
        return await callback()
    c.ingest.publish_volatile = AsyncMock(side_effect=publish)
    await collect_live(c, datetime.now(CHINA))
    assert c.health()["storage"] == "redis_only"
    await c.execute(start="2026-10-30", end="2026-11-02")
    assert len(published) == 2 and c.health()["storage"] == "mysql"
    assert c.health()["notice"] == "" and c.health()["requests"] == 4
    c.stats["error"] = "previous failure"
    idle(c, "非采样时段")
    assert c.health()["storage"] == "none" and c.health()["error"] == ""
    assert c.health()["requests"] == c.health()["pages"] == 0


async def test_daily_failure_is_recorded_once_through_dispatch(monkeypatch):
    c, _, _ = collector()
    c.intraday = True
    async def dispatch(collector, **kwargs):
        return await collector._execute(sample_dates=[], **kwargs)
    monkeypatch.setattr("empire.features.graymarket.intraday.dispatch", dispatch)
    with pytest.raises(ValueError, match="抽样日期"):
        await c.execute()
    assert c.records.add_error.await_count == 1


@pytest.mark.skipif(os.environ.get("EMPIRE_REDIS_REAL") != "1", reason="isolated real Redis")
async def test_changes_stale_fixed_version_eviction_and_replay(monkeypatch):
    import empire.features.graymarket.intraday_store as module
    from empire.features.graymarket.intraday_query import browse_live
    client = create_client(load_config()["redis"])
    prefix = "empire:test:" + uuid4().hex
    redis = SimpleNamespace(client=client, prefix=prefix)
    store = IntradayStore(redis)
    now = datetime.now(CHINA) - timedelta(minutes=5)
    stamp = now.date().isoformat()
    assembly = DayAssembly(parsed(response(total=201)))
    for page in (2, 3):
        assembly.add(parsed(response(total=201, page=page), page=page))
    rows = assembly.finish()
    try:
        assert (await store.save(stamp, rows, now, now + timedelta(seconds=1)))["changed"]
        old = await store.read(stamp)
        ttl = await client.pttl(store.body_key(old["version"]))
        assert not (await store.save(stamp, rows, now + timedelta(seconds=2), now + timedelta(seconds=3)))["changed"]
        assert await client.pttl(store.body_key(old["version"])) <= ttl
        assert (await store.save(stamp, rows, now, now))["stale"]
        context = SimpleNamespace(optional=lambda _: redis)
        filters = (3, "graymarket", "", stamp, "", "")
        first = await browse_live(context, filters, None, None)
        assert len(first["rows"]) == 200 and first["next"]
        changed = [list(r) for r in rows]
        changed[0][1] = "修订名称"
        assert (await store.save(stamp, changed, now + timedelta(seconds=4), now + timedelta(seconds=5)))["changed"]
        assert (await store.read(stamp, version=old["version"]))["rows"] == rows
        second = await browse_live(context, filters, first["next"], None)
        assert len(second["rows"]) == 1 and not second["next"]
        monkeypatch.setattr(module, "MAX_SNAPSHOTS", 1)
        changed[0][1] = "再次修订"
        assert (await store.save(stamp, changed, now + timedelta(seconds=6), now + timedelta(seconds=7)))["evicted"] == 2
        with pytest.raises(ValueError, match="过期"):
            await browse_live(context, filters, first["next"], None)
        assert await client.zcard(store.keys()[1]) == 1
        assert not await client.exists(prefix + ":ingest")
    finally:
        keys = [k async for k in client.scan_iter(match=prefix + ":*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()
