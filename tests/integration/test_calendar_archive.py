import asyncio
import copy
import os
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.plugins.datasets.trade_calendar import month_dates

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly")]


@pytest.fixture
async def calendar_db():
    cfg = copy.deepcopy(load_config())
    token = uuid4().hex
    source = "test-" + token
    cfg["redis"]["namespace"] = "empire:test:" + token
    cfg["archive"]["interval_seconds"] = 3600
    manager = build_manager(cfg)
    query = manager.entries["data.trade_calendar"].plugin
    query.source, query.job_key = source, "calendar-test"
    mysql = store = None
    try:
        await manager.start("pipeline.ingest")
        await manager.start("data.trade_calendar")
        await asyncio.sleep(.02)
        ingest, archive = manager.registry.get("ingest.publish"), manager.registry.get("archive.worker")
        mysql, store = manager.registry.get("mysql.store"), manager.registry.get("redis.store")
        async def publish(month="2027-01", *, trading=True, observed=None, flush=True, batch=None, page=1):
            batch = batch or uuid4().hex
            rows = [{"trade_date": day.isoformat(), "is_trade": trading} for day in month_dates(month)]
            value = make_envelope(source=source, dataset="calendar.month", job_key="calendar-test",
                business_key=f"{batch}:{month}", run_id=batch, batch_id=batch,
                payload={"month": month, "page": page, "rows": rows})
            if observed:
                value = value.model_copy(update={"observed_at": observed})
            state = await ingest.checkpoint("calendar-test")
            await ingest.publish_page([value], job_key="calendar-test", expected_revision=state["revision"], cursor={"page": page})
            if flush:
                await archive.flush()
            return value
        yield manager, query, publish
    finally:
        await manager.stop("pipeline.archive", cascade=True)
        if mysql:
            def cleanup():
                with mysql.engine.begin() as conn:
                    conn.execute(text("DELETE FROM trade_calendar WHERE source=:source"), {"source": source})
            await mysql.read(cleanup)
        if store:
            keys = [k async for k in store.client.scan_iter(match=cfg["redis"]["namespace"] + ":*")]
            if keys:
                assert all(k.startswith("empire:test:" + token + ":") for k in keys)
                await store.client.delete(*keys)
        await manager.shutdown()


async def test_repeat_has_no_dml_and_noop_observation_protects_against_old_month(calendar_db):
    manager, query, publish = calendar_db
    mysql = manager.registry.get("mysql.store")
    earlier = datetime.now(UTC) - timedelta(minutes=10)
    await publish(observed=earlier)
    before = await query.month("2027-01")
    assert before["complete"] and len(before["rows"]) == 31
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "trade_calendar" in statement:
            writes.append(statement)
    event.listen(mysql.engine, "before_cursor_execute", capture)
    try:
        await publish(observed=earlier + timedelta(minutes=3))
        assert not writes and await query.month("2027-01") == before
        await publish(trading=False, observed=earlier + timedelta(minutes=2))
        assert not writes and await query.month("2027-01") == before
        await publish(trading=False, observed=earlier + timedelta(minutes=4))
        assert len(writes) == 1 and all(not r["is_trade"] for r in (await query.month("2027-01"))["rows"])
        # Historical data from another month is never removed by maintenance.
        await publish("1990-12")
        assert len((await query.month("1990-12"))["rows"]) == 13
    finally:
        event.remove(mysql.engine, "before_cursor_execute", capture)


async def test_commit_ack_failure_replay_and_sql_outage_keep_data(calendar_db, monkeypatch):
    manager, query, publish = calendar_db
    archive, mysql = manager.registry.get("archive.worker"), manager.registry.get("mysql.store")
    store = manager.registry.get("redis.store")
    original_ack = archive.acknowledge
    async def ack_failure(ids):
        raise ConnectionError("after commit")
    monkeypatch.setattr(archive, "acknowledge", ack_failure)
    with pytest.raises(ConnectionError):
        await publish()
    assert (await query.month("2027-01"))["complete"]
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive, "acknowledge", original_ack)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    original_write = mysql.archive
    async def offline(records):
        raise ConnectionError("SQL offline")
    monkeypatch.setattr(mysql, "archive", offline)
    with pytest.raises(ConnectionError):
        await publish("2027-02")
    assert not (await query.month("2027-02"))["rows"]
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(mysql, "archive", original_write)
    await archive.flush()
    assert (await query.month("2027-02"))["complete"]


async def test_invalid_month_does_not_replace_existing_or_confirm_run(calendar_db):
    manager, query, publish = calendar_db
    await publish()
    before = await query.month("2027-01")
    batch = uuid4().hex
    bad = make_envelope(source=query.source, dataset="calendar.month", job_key=query.job_key,
        business_key=batch, run_id=batch, batch_id=batch,
        payload={"page": 1, "month": "2027-01", "rows": []})
    store = manager.registry.get("redis.store")
    await store.client.xadd(store.stream, {"envelope": bad.model_dump_json()})
    await manager.registry.get("archive.worker").flush()
    assert await query.month("2027-01") == before
    assert (await query.page_status(batch, 1))["status"] == "invalid"
    assert len(await manager.registry.get("collection.records").list_errors("calendar-test")) == 1


async def test_sql_coverage_planning_survives_lost_redis_checkpoint(calendar_db):
    manager, query, publish = calendar_db
    await publish("1990-12")
    store = manager.registry.get("redis.store")
    await store.client.delete(f"{store.prefix}:checkpoint:calendar-test")
    plan = await query.plan(date(2026, 9, 23))
    assert plan["months"][0] == "1991-01"
    assert plan["months"][-1] == "2027-12"
    assert len(plan["months"]) == 444
