import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly"
)]


@pytest.fixture
async def stock_database():
    cfg = copy.deepcopy(load_config(os.environ.get("EMPIRE_CONFIG")))
    token = uuid4().hex
    cfg["redis"]["namespace"] = f"empire:test:{token}"
    cfg["archive"]["interval_seconds"] = 3600
    manager = build_manager(cfg)
    manager.entries["data.stocks"].plugin.source = f"test-{token}"
    manager.entries["data.stocks"].plugin.job_key = "test"
    manager.entries["data.stocks"].plugin.project_id = "test"
    events = []
    snapshots = []
    last_started = datetime.now(UTC)
    try:
        await manager.start("pipeline.ingest")
        await manager.start("data.stocks")
        await manager.start("infra.archive_confirmation")
        ingest = manager.registry.get("ingest.publish")
        archive = manager.registry.get("archive.worker")
        mysql = manager.registry.get("mysql.store")
        redis = manager.registry.get("redis.store")
        query = manager.registry.get("stocks.query")
        await asyncio.sleep(.03)

        def snapshot():
            nonlocal last_started
            # Windows clock resolution can give consecutive batches equal timestamps;
            # these tests explicitly model chronological batches, not UUID tie breaks.
            last_started = max(datetime.now(UTC), last_started + timedelta(microseconds=1))
            value = {"snapshot_id": uuid4().hex, "started_at": last_started.isoformat(),
                     "node": "hs_a", "expected_count": 2, "page_size": 2}
            snapshots.append(value["snapshot_id"])
            return value

        async def publish(kind, batch, **payload):
            state = await ingest.checkpoint("test")
            event = make_envelope(
                source=f"test-{token}", dataset=f"stock.universe.{kind}",
                business_key=f"{batch['snapshot_id']}:{kind}:{payload.get('page', '')}",
                job_key="test", run_id=token, batch_id=batch["snapshot_id"], payload={**batch, **payload},
            )
            events.append(event.event_id)
            await ingest.publish_page([event], job_key="test", expected_revision=state["revision"], cursor={})
            await archive.flush()
            return event

        yield snapshot, publish, query, manager
    finally:
        await manager.stop("pipeline.archive", cascade=True)
        if manager.entries["infra.mysql"].state == "RUNNING":
            def cleanup():
                with mysql.engine.begin() as connection:
                    connection.execute(text("DELETE FROM stock WHERE source=:source"),
                                       {"source": f"test-{token}"})
                    connection.execute(text("DELETE FROM collection_state WHERE source=:source"),
                                       {"source": f"test-{token}"})
            await mysql.control(cleanup)
        if manager.entries["infra.redis"].state == "RUNNING":
            keys = [key async for key in redis.client.scan_iter(f"{redis.prefix}:*")]
            if keys:
                await redis.client.delete(*keys)
        await manager.shutdown()


ROWS = [{"symbol": "sz000001", "code": "000001", "name": "平安银行"},
        {"symbol": "sh600519", "code": "600519", "name": "贵州茅台"}]


async def test_stock_hash_hit_avoids_sql_and_removes_all_pages(stock_database, monkeypatch):
    snapshot, publish, query, manager = stock_database
    archive = manager.registry.get("archive.worker")
    mysql = manager.registry.get("mysql.store")
    store = manager.registry.get("redis.store")
    async def complete():
        batch = snapshot()
        await publish("page", batch, page=1, rows=ROWS)
        await publish("complete", batch, pages=1, collected=2, count_after=2, terminal_rows=[])
    await complete()
    original = mysql.archive
    calls = []
    async def capture(records):
        calls.append(records)
        return await original(records)
    async def forbidden(*args):
        raise AssertionError("cache hit must not read MySQL")
    monkeypatch.setattr(mysql, "archive", capture)
    monkeypatch.setattr(mysql, "read", forbidden)
    await complete()
    assert not calls and await store.client.xlen(store.stream) == 0
    await archive.fingerprints.invalidate("stocks", query.source)
    # committed is display progress only; a lost fingerprint must consult SQL.
    monkeypatch.setattr(mysql, "read", type(mysql).read.__get__(mysql))
    await complete()
    assert len(calls) == 1 and await store.client.xlen(store.stream) == 0
    monkeypatch.undo()


async def test_stock_hash_hit_without_progress_key_still_skips_all_sql(stock_database, monkeypatch):
    snapshot, publish, query, manager = stock_database
    async def complete():
        batch = snapshot()
        await publish("page", batch, page=1, rows=ROWS)
        await publish("complete", batch, pages=1, collected=2, count_after=2, terminal_rows=[])
    await complete()
    store = manager.registry.get("redis.store")
    await store.client.delete(f"{store.prefix}:stocks:committed:{query.source}")
    async def forbidden(*args, **kwargs):
        raise AssertionError("Stock fingerprint hit must not access MySQL")
    mysql = manager.registry.get("mysql.store")
    monkeypatch.setattr(mysql, "read", forbidden)
    monkeypatch.setattr(mysql, "archive", forbidden)
    await complete()
    assert await store.client.xlen(store.stream) == 0
    monkeypatch.undo()


async def test_identical_stock_list_has_no_dml_and_late_batch_cannot_regress(stock_database):
    snapshot, publish, query, manager = stock_database
    first = snapshot()
    await publish("page", first, page=1, rows=ROWS)
    await publish("complete", first, pages=1, collected=2, count_after=2, terminal_rows=[])
    delayed = snapshot()
    identical = snapshot()
    mysql = manager.registry.get("mysql.store")
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "stock" in statement:
            writes.append(statement)
    event.listen(mysql.engine, "before_cursor_execute", capture)
    try:
        await publish("page", identical, page=1, rows=ROWS)
        await publish("complete", identical, pages=1, collected=2, count_after=2, terminal_rows=[])
        assert not writes
        assert (await manager.registry.get("archive.confirmation").stock_status(
            query.source, query.job_key, query.project_id, identical["snapshot_id"]))["status"] == "complete"
        assert (await query.list_stocks())["snapshot"]["snapshot_id"] == first["snapshot_id"]
        assert "verified_snapshot_id" not in await query.list_stocks()
        await publish("page", delayed, page=1, rows=[{**ROWS[0], "name": "过时内容"}, ROWS[1]])
        await publish("complete", delayed, pages=1, collected=2, count_after=2, terminal_rows=[])
        assert not writes
        assert (await query.list_stocks())["rows"][0]["name"] == ROWS[0]["name"]
    finally:
        event.remove(mysql.engine, "before_cursor_execute", capture)


async def test_only_complete_snapshot_visible_and_partial_refresh_preserves_previous(stock_database):
    snapshot, publish, query, manager = stock_database
    first = snapshot()
    await publish("start", first, count_before=2)
    await publish("page", first, page=1, rows=ROWS)
    assert (await query.list_stocks())["total"] == 0
    await publish("complete", first, pages=1, collected=2, count_after=2, terminal_rows=[])
    listing = await query.list_stocks()
    assert listing["total"] == 2
    assert {row["source"] for row in listing["rows"]} == {query.source}
    assert listing["rows"][0]["unified_code"] == "000001.SZ"
    assert listing["rows"][0]["name"] == "平安银行"
    assert (await query.list_stocks("贵州"))["total"] == 1
    second = snapshot()
    await publish("start", second, count_before=2)
    await publish("page", second, page=1, rows=[{**ROWS[0], "name": "新名称"}, ROWS[1]])
    assert (await query.list_stocks())["snapshot"]["snapshot_id"] == first["snapshot_id"]
    await publish("complete", second, pages=1, collected=2, count_after=2, terminal_rows=[])
    assert (await query.list_stocks())["snapshot"]["snapshot_id"] == second["snapshot_id"]
    assert await manager.registry.get("archive.confirmation").stock_status(
        query.source, query.job_key, query.project_id, first["snapshot_id"]) is None
    mysql = manager.registry.get("mysql.store")

    def retained_counts():
        with mysql.engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM stock WHERE source=:source"),
                                {"source": query.source}).scalar_one()

    assert await mysql.control(retained_counts) == 2
    # Delayed old data cannot recreate the retired complete list or its raw pages.
    await publish("page", first, page=1, rows=ROWS)
    await publish("complete", first, pages=1, collected=2, count_after=2, terminal_rows=[])
    assert await manager.registry.get("archive.confirmation").stock_status(
        query.source, query.job_key, query.project_id, first["snapshot_id"]) is None
    assert (await query.list_stocks())["snapshot"]["snapshot_id"] == second["snapshot_id"]


async def test_replacement_removes_missing_stock_updates_name_and_bounds_failed_staging(stock_database):
    snapshot, publish, query, manager = stock_database
    first = snapshot()
    await publish("page", first, page=1, rows=ROWS)
    await publish("complete", first, pages=1, collected=2, count_after=2, terminal_rows=[])
    failed = snapshot()
    await publish("complete", failed, pages=1, collected=2, count_after=2, terminal_rows=[])
    assert (await query.list_stocks())["total"] == 2
    replacement = snapshot()
    replacement.update(expected_count=1)
    await publish("page", replacement, page=1, rows=[{**ROWS[0], "name": "更新名称"}])
    assert (await manager.registry.get("archive.confirmation").stock_status(
        query.source, query.job_key, query.project_id, failed["snapshot_id"]))["status"] == "invalid"
    assert (await query.list_stocks())["total"] == 2
    await publish("complete", replacement, pages=1, collected=1, count_after=1, terminal_rows=[])
    listing = await query.list_stocks()
    assert listing["total"] == 1
    assert listing["rows"][0]["name"] == "更新名称"
    mysql = manager.registry.get("mysql.store")

    def counts():
        with mysql.engine.connect() as conn:
            return conn.execute(text("SELECT COUNT(*) FROM collection_state WHERE source=:source"),
                                {"source": query.source}).scalar_one()

    assert await mysql.control(counts) == 1


async def test_page_and_completion_replay_do_not_duplicate_members(stock_database):
    snapshot, publish, query, manager = stock_database
    batch = snapshot()
    await publish("page", batch, page=1, rows=ROWS)
    await publish("page", batch, page=1, rows=ROWS)
    for _attempt in range(2):
        await publish("complete", batch, pages=1, collected=2, count_after=2, terminal_rows=[])
    assert (await query.list_stocks())["total"] == 2
    await publish("page", batch, page=1, rows=[{**ROWS[0], "name": "事后修订"}, ROWS[1]])
    assert (await query.list_stocks())["rows"][0]["name"] == "平安银行"
    assert (await manager.registry.get("archive.confirmation").stock_status(
        query.source, query.job_key, query.project_id, batch["snapshot_id"]))["status"] == "complete"


async def test_replacement_cleanup_failure_rolls_back_publication(stock_database, monkeypatch):
    from empire.plugins.datasets import stocks
    snapshot, publish, query, manager = stock_database
    first = snapshot()
    await publish("page", first, page=1, rows=ROWS)
    await publish("complete", first, pages=1, collected=2, count_after=2, terminal_rows=[])
    second = snapshot()
    await publish("page", second, page=1, rows=[{**ROWS[0], "name": "新名称"}, ROWS[1]])
    original = stocks.insert_rows

    def fail_after_delete(*args):
        original(*args)
        raise RuntimeError("injected replacement failure")

    monkeypatch.setattr(stocks, "insert_rows", fail_after_delete)
    with pytest.raises(RuntimeError, match="injected"):
        await publish("complete", second, pages=1, collected=2, count_after=2, terminal_rows=[])
    assert (await query.list_stocks())["snapshot"]["snapshot_id"] == first["snapshot_id"]
    assert await manager.registry.get("archive.confirmation").stock_status(
        query.source, query.job_key, query.project_id, second["snapshot_id"]) is None
    monkeypatch.setattr(stocks, "insert_rows", original)
    await manager.registry.get("archive.worker").flush()
    assert (await query.list_stocks())["snapshot"]["snapshot_id"] == second["snapshot_id"]
    assert await manager.registry.get("archive.confirmation").stock_status(
        query.source, query.job_key, query.project_id, first["snapshot_id"]) is None


async def test_missing_page_or_changed_page_never_becomes_current(stock_database):
    snapshot, publish, query, manager = stock_database
    missing = snapshot()
    await publish("complete", missing, pages=1, collected=2, count_after=2, terminal_rows=[])
    assert (await manager.registry.get("archive.confirmation").stock_status(
        query.source, query.job_key, query.project_id, missing["snapshot_id"]))["status"] == "invalid"
    changed = snapshot()
    await publish("page", changed, page=1, rows=ROWS)
    await publish("page", changed, page=1, rows=[{**ROWS[0], "name": "名称修订"}, ROWS[1]])
    await publish("complete", changed, pages=1, collected=2, count_after=2, terminal_rows=[])
    assert (await manager.registry.get("archive.confirmation").stock_status(
        query.source, query.job_key, query.project_id, changed["snapshot_id"]))["status"] == "invalid"
    assert (await query.list_stocks())["total"] == 0


async def test_market_filter_counts_entire_snapshot_and_composes_with_search(stock_database):
    snapshot, publish, query, _ = stock_database
    batch = snapshot()
    rows = ROWS + [
        {"symbol": "sz000002", "code": "000002", "name": "万科 A"},
        {"symbol": "sh600000", "code": "600000", "name": "浦发银行"},
        {"symbol": "bj920000", "code": "920000", "name": "安徽凤凰"},
        {"symbol": "bj920001", "code": "920001", "name": "纬达光电"},
    ]
    rows.sort(key=lambda row: row["symbol"], reverse=True)
    batch.update(expected_count=len(rows), page_size=len(rows))
    await publish("page", batch, page=1, rows=rows)
    await publish("complete", batch, pages=1, collected=len(rows), count_after=len(rows), terminal_rows=[])
    assert (await query.list_stocks())["total"] == 6
    for market in ("SH", "SZ", "BJ"):
        first = await query.list_stocks("", 0, 1, market)
        second = await query.list_stocks("", 1, 1, market)
        assert first["total"] == second["total"] == 2
        assert first["rows"][0]["market"] == second["rows"][0]["market"] == market
        assert first["rows"][0]["unified_code"] != second["rows"][0]["unified_code"]
    assert (await query.list_stocks("银行", market="SH"))["total"] == 1
    assert (await query.list_stocks("银行", market="BJ"))["total"] == 0
    with pytest.raises(ValueError, match="不支持的股票市场"):
        await query.list_stocks(market="invalid")
