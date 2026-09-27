"""Isolated real Redis scheduling, plus real SQL snapshot/restart regression."""
import asyncio
import os
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from test_news_archive import news_db as news_db
from test_stock_archive import ROWS
from test_stock_archive import stock_database as stock_database

from empire.contracts.data import UnsupportedSchema, make_envelope
from empire.core.config import load_config
from empire.plugins.datasets.astock import DatasetPlugin
from empire.plugins.datasets.news import normalize_source
from empire.plugins.datasets.trade_calendar import month_dates
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.archive import ArchivePlugin
from empire.plugins.pipeline.archive_queue import SCAN_WINDOW

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Explicit integration opt-in required")]


@pytest.fixture
async def archive_case():
    client = create_client(load_config()["redis"])
    prefix = "empire:test:" + uuid4().hex
    worker = ArchivePlugin({"work_max_units": 3, "work_time_ms": 5000, "scan_time_ms": 5000})
    worker.redis = SimpleNamespace(client=client, prefix=prefix, stream=prefix + ":stream")
    worker.catalog = DatasetPlugin()
    worker.records = SimpleNamespace(add_error=AsyncMock(), add_archive=AsyncMock())
    worker.mysql = SimpleNamespace(read=AsyncMock(return_value={}))
    worker.states = SimpleNamespace(read=None)
    worker.fingerprints = SimpleNamespace(get=AsyncMock(return_value={}))
    writes = []

    async def sink(envelope, data):
        writes.append((envelope.job_key, data.get("page"), envelope.batch_id))
        return {"status": "complete", "row_count": data.get("row_count", data.get("expected_count", 0))}
    worker._archive_data = sink  # SQL correctness is separately exercised below and by archive regressions.

    async def enqueue(project, page, *, batch="run"):
        row = normalize_source({"id": page, "rich_text": "测试正文", "create_time": "2026-09-23 08:00:00",
                                "update_time": "2026-09-23 08:00:00", "tag": [], "is_focus": 0})
        event = make_envelope(source="test", dataset="news.flash.page", business_key=f"{project}:{page}",
            job_key=project, run_id=batch, batch_id=batch, payload={"page": page, "rows": [row]})
        ident = await client.xadd(worker.redis.stream, {"envelope": event.model_dump_json()})
        return ident
    try:
        yield worker, writes, enqueue
    finally:
        keys = [key async for key in client.scan_iter(match=prefix + ":*")]
        if keys:
            await client.delete(*keys)
        await client.aclose()


async def test_large_project_does_not_drain_before_other_projects(archive_case):
    worker, writes, enqueue = archive_case
    for page in range(1, 21):
        await enqueue("large", page)
    await enqueue("news", 1)
    calendar = make_envelope(source="test", dataset="calendar.month", business_key="2026-09",
        job_key="calendar-project", run_id="run", batch_id="calendar", payload={"page": 1,
        "month": "2026-09", "rows": [{"trade_date": day.isoformat(), "is_trade": True}
                                     for day in month_dates("2026-09")]})
    await worker.redis.client.xadd(worker.redis.stream, {"envelope": calendar.model_dump_json()})
    await worker.flush()
    assert [row[0] for row in writes] == ["large", "news", "calendar-project"]
    assert await worker.redis.client.xlen(worker.redis.stream) == 19
    assert worker.health()["work_units"] == 3
    for _ in range(7):
        await worker.flush()
    assert [row[1] for row in writes if row[0] == "large"] == list(range(1, 21))
    assert not worker.queue.ids


async def test_scan_budget_advances_past_backlog_and_discovery_is_not_restarted(archive_case):
    worker, writes, enqueue = archive_case
    worker.limits = replace(worker.limits, scan_max_messages=2, work_max_units=1)
    for page in range(1, 11):
        await enqueue("large", page)
    await enqueue("small", 1)
    cursors = []
    for _ in range(8):
        await worker.flush()
        assert worker.health()["scan_messages"] <= 2
        cursors.append(worker.queue.cursor)
    assert any(row[0] == "small" for row in writes)
    assert len(set(cursors[:5])) == 5


async def test_new_tail_behind_in_progress_cutoff_keeps_continuation_wake(archive_case):
    worker, writes, enqueue = archive_case
    worker.limits = replace(worker.limits, scan_max_messages=1, work_max_units=1)
    for page in (1, 2, 3):
        await enqueue("news", page)
    await worker.flush()  # Captures a cutoff at page 3, but only reads page 1.
    await enqueue("news", 4)  # Its wake can be consumed while still scanning pages 2/3.
    await worker.flush()
    await worker.flush()
    assert worker.queue.cutoff is None and worker.queue.more_scan
    assert worker.queue.wait_seconds() <= .01
    await worker.flush()
    assert [row[1] for row in writes] == [1, 2, 3, 4]


@pytest.mark.parametrize("backlog", [1000, 3000])
async def test_tail_project_runs_before_large_backlog_is_drained(archive_case, backlog):
    worker, writes, enqueue = archive_case
    worker.limits = replace(worker.limits, scan_max_messages=100, work_max_units=1)
    for page in range(1, backlog + 1):
        await enqueue("large", page)
    await enqueue("tail", 1)
    for _ in range(backlog // 100 + 3):
        await worker.flush()
        assert worker.health()["scan_messages"] <= 100
        assert worker.health()["scan_bytes"] <= worker.limits.scan_max_bytes
        assert len(worker.queue.ids) <= backlog + 1
    assert any(row[0] == "tail" for row in writes)
    assert len(writes) <= backlog // 100 + 3
    assert await worker.redis.client.xlen(worker.redis.stream) == backlog + 1 - len(writes)


async def test_byte_budget_and_oversized_record_never_delete_unprocessed_data(archive_case):
    worker, _, enqueue = archive_case
    first = await enqueue("a", 1)
    await enqueue("b", 1)
    client, stream = worker.redis.client, worker.redis.stream
    fields = (await client.xrange(stream, min=first, max=first))[0][1]
    budget = len(first) + sum(len(k.encode()) + len(v.encode()) for k, v in fields.items()) + 1
    rows, size, blocked, required = await client.eval(SCAN_WINDOW, 1, stream, "-", "+", 100, budget)
    assert rows and size <= budget
    assert all(row[0] == first for row in rows)
    assert blocked and required > 0
    worker.limits = replace(worker.limits, scan_max_bytes=10)
    with pytest.raises(ValueError, match="scan_max_bytes"):
        await worker.flush()
    assert await client.xlen(stream) == 2
    worker.limits = replace(worker.limits, scan_max_bytes=budget)
    await worker.flush()
    assert worker.health()["scan_bytes"] <= budget


async def test_failed_project_keeps_queue_but_other_project_finishes(archive_case):
    worker, writes, enqueue = archive_case
    bad = await enqueue("bad", 1)
    await enqueue("good", 1)
    sink = worker._archive_data

    async def failure(envelope, data):
        if envelope.job_key == "bad":
            raise ConnectionError("isolated sink failure")
        return await sink(envelope, data)
    worker._archive_data = failure
    with pytest.raises(ConnectionError):
        await worker.flush()
    assert [row[0] for row in writes] == ["good"]
    assert (await worker.redis.client.xrange(worker.redis.stream))[0][0] == bad
    await worker.flush(retry_failed=False)
    assert worker.health()["status"] == "degraded"
    worker._archive_data = sink
    await worker.flush()
    assert await worker.redis.client.xlen(worker.redis.stream) == 0


async def test_cancelled_work_returns_to_scheduler_and_commit_ack_replay_is_safe(archive_case):
    worker, writes, enqueue = archive_case
    await enqueue("a", 1)
    entered = asyncio.Event()
    sink = worker._archive_data

    async def paused(*args):
        entered.set()
        await asyncio.Event().wait()
    worker._archive_data = paused
    task = asyncio.create_task(worker.flush())
    await asyncio.wait_for(entered.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await worker.redis.client.xlen(worker.redis.stream) == 1
    worker._archive_data = sink
    await worker.flush()
    assert len(writes) == 1 and not worker.queue.ids


async def test_unknown_schema_still_pauses_globally_without_skipping_message(archive_case):
    worker, writes, enqueue = archive_case
    ident = await enqueue("known", 1)
    raw = (await worker.redis.client.xrange(worker.redis.stream, min=ident, max=ident))[0][1]["envelope"]
    from empire.contracts.data import Envelope
    value = Envelope.model_validate_json(raw).model_copy(update={"schema_version": 999})
    await worker.redis.client.xadd(worker.redis.stream, {"envelope": value.model_dump_json()})
    for _ in range(2):
        with pytest.raises(UnsupportedSchema):
            await worker.flush()
        assert worker.blocked and not writes
        assert await worker.redis.client.xlen(worker.redis.stream) == 2


@pytest.mark.parametrize("position", [0, 1, 2])
async def test_known_project_schema_isolated_and_recovers_without_deleting_unknown(archive_case, position):
    from empire.contracts.data import Envelope

    worker, writes, enqueue = archive_case
    good = await enqueue("sina-news-v1", 1)
    raw = (await worker.redis.client.xrange(worker.redis.stream, min=good, max=good))[0][1]["envelope"]
    value = Envelope.model_validate_json(raw).model_copy(update={"schema_version": 999})
    # Place unknown before, between or after independent project messages.
    for index in range(3):
        if index == position:
            unknown = await worker.redis.client.xadd(worker.redis.stream, {"envelope": value.model_dump_json()})
        else:
            await enqueue("independent", index + 10)
    await worker.flush()
    assert not worker.blocked
    assert worker.blocked_projects == {"sina-news"}
    assert worker.records.add_error.call_args.args[0] == "sina-news"
    assert all(job == "independent" for job, _, _ in writes)
    assert await worker.redis.client.xlen(worker.redis.stream) == 2
    assert await worker.redis.client.xrange(worker.redis.stream, min=unknown, max=unknown)
    assert worker.queue.wait_seconds(worker.blocked_projects) > .01
    original = worker.catalog.mapping

    def restored(envelope):
        return original(envelope.model_copy(update={"schema_version": 1}))

    worker.catalog.mapping = restored
    # Restore the reader and normalizer together, as a supported contract upgrade would.
    normalize = worker.catalog.normalize
    worker.catalog.normalize = lambda envelope: normalize(envelope.model_copy(update={"schema_version": 1}))
    await worker.flush()
    assert not worker.blocked_projects
    assert await worker.redis.client.xlen(worker.redis.stream) == 0


async def test_isolation_of_indexed_message_reuses_capacity(archive_case):
    from empire.contracts.data import Envelope

    worker, _, enqueue = archive_case
    worker.queue.limit = 1
    ident = await enqueue("sina-news-v1", 1)
    await worker._scan()
    raw = (await worker.redis.client.xrange(worker.redis.stream, min=ident, max=ident))[0][1]["envelope"]
    envelope = Envelope.model_validate_json(raw)
    await worker._record_invalid(ident, raw, envelope, UnsupportedSchema("reader unavailable"), schema=True)
    assert worker.indexed_count == 1
    assert worker.blocked_projects == {"sina-news"}
    assert await worker.redis.client.xlen(worker.redis.stream) == 1


async def test_future_malformed_envelope_is_retained_and_blocks_globally(archive_case):
    worker, writes, enqueue = archive_case
    ident = await worker.redis.client.xadd(worker.redis.stream,
        {"envelope": '{"schema_version":999,"job_key":"sina-news-v1"}'})
    await enqueue("independent", 1)
    with pytest.raises(UnsupportedSchema):
        await worker.flush()
    assert worker.blocked and not writes
    assert await worker.redis.client.xrange(worker.redis.stream, min=ident, max=ident)


async def test_split_snapshot_and_restart_do_not_publish_partial_data(stock_database):
    snapshot, publish, query, manager = stock_database
    archive = manager.registry.get("archive.worker")
    store = manager.registry.get("redis.store")
    batch = snapshot()
    values = []
    for kind, payload in (("page", {"page": 1, "rows": ROWS}),
                          ("complete", {"pages": 1, "collected": 2, "count_after": 2, "terminal_rows": []})):
        values.append(make_envelope(source=query.source, dataset="stock.universe." + kind,
            business_key=batch["snapshot_id"] + kind, job_key="test", run_id=uuid4().hex,
            batch_id=batch["snapshot_id"], payload={**batch, **payload}))
    for value in values:
        await store.client.xadd(store.stream, {"envelope": value.model_dump_json()})
    archive.limits = replace(archive.limits, scan_max_messages=1)
    original_scan = archive._scan
    scan_calls = 0
    resident_waiting = asyncio.Event()
    async def pause_resident_continuation():
        nonlocal scan_calls
        scan_calls += 1
        if scan_calls == 2:
            resident_waiting.set()
            await archive.stop_event.wait()
            return
        await original_scan()
    archive._scan = pause_resident_continuation
    await archive.flush()
    await asyncio.wait_for(resident_waiting.wait(), 2)
    assert (await query.list_stocks())["total"] == 0
    assert await store.client.xlen(store.stream) == 2
    # Restart destroys only the disposable ID index, not pending business messages.
    await manager.stop("pipeline.archive", cascade=True)
    await manager.start("pipeline.archive")
    archive = manager.registry.get("archive.worker")
    for _ in range(4):
        await archive.flush()
    assert (await query.list_stocks())["total"] == 2
    assert await store.client.xlen(store.stream) == 0


async def test_parked_partial_batch_is_not_reread_on_unchanged_flush(stock_database, monkeypatch):
    snapshot, publish, _, manager = stock_database
    batch = snapshot()
    await publish("page", batch, page=1, rows=ROWS)
    archive = manager.registry.get("archive.worker")
    original = archive._load_records
    reads = AsyncMock(wraps=original)
    monkeypatch.setattr(archive, "_load_records", reads)
    for _ in range(5):
        await archive.flush()
    assert reads.await_count == 0
    assert len(archive.queue.ids) == 1


async def test_small_index_drains_ready_pages_instead_of_deadlocking(archive_case):
    worker, writes, enqueue = archive_case
    worker.queue.limit = 2
    for page in range(1, 7):
        await enqueue("news", page)
    for _ in range(4):
        await worker.flush()
        assert len(worker.queue.ids) <= 2
    assert len(writes) == 6
    assert await worker.redis.client.xlen(worker.redis.stream) == 0


async def test_work_time_budget_yields_between_indivisible_business_units(archive_case):
    worker, writes, enqueue = archive_case
    for page in range(1, 4):
        await enqueue("news", page)
    worker.limits = replace(worker.limits, work_time_ms=1)
    sink = worker._archive_data

    async def slow(*args):
        await asyncio.sleep(.02)
        return await sink(*args)
    worker._archive_data = slow
    await worker.flush()
    assert len(writes) == worker.health()["work_units"] == 1
    assert await worker.redis.client.xlen(worker.redis.stream) == 2


async def test_scan_time_budget_yields_between_redis_windows(archive_case, monkeypatch):
    worker, _, enqueue = archive_case
    for page in range(1, 5):
        await enqueue("news", page)
    worker.limits = replace(worker.limits, batch_size=1, scan_time_ms=1)
    original = worker.redis.client.eval

    async def slow(script, *args):
        if script == SCAN_WINDOW:
            await asyncio.sleep(.02)
        return await original(script, *args)
    monkeypatch.setattr(worker.redis.client, "eval", slow)
    await worker.flush()
    assert worker.health()["scan_messages"] == 1
    assert worker.health()["scan_more"]


async def test_resident_worker_continues_quanta_without_waiting_for_recovery_scan(news_db):
    manager, publish, query = news_db
    archive = manager.registry.get("archive.worker")
    archive.limits = replace(archive.limits, scan_max_messages=1, work_max_units=1)
    for ident in range(101, 111):
        await publish(ident, flush=False)
    deadline = asyncio.get_running_loop().time() + 10
    while asyncio.get_running_loop().time() < deadline:
        if (await query.list_news())["total"] == 10:
            break
        await asyncio.sleep(.02)
    if (await query.list_news())["total"] != 10:
        pytest.fail(f"health={archive.health()} cursor={archive.queue.cursor} "
            f"cutoff={archive.queue.cutoff} stable={archive.queue.stable_cutoff} "
            f"ready={[(p, list(v)) for p, v in archive.queue.ready.items()]} "
            f"batches={[(b.key, len(b.ids), b.checked, b.dirty) for b in archive.queue.batches.values()]} "
            f"wake={archive.wake_event.is_set()} task_done={archive.task.done()}")
    store = manager.registry.get("redis.store")
    # Commit precedes ACK, so allow the in-flight Redis confirmation to settle.
    for _ in range(100):
        if await store.client.xlen(store.stream) == 0:
            break
        await asyncio.sleep(.01)
    assert await store.client.xlen(store.stream) == 0
