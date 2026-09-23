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
from empire.plugins.datasets.news import normalize_source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly"
)]


@pytest.fixture
async def news_db():
    cfg = copy.deepcopy(load_config())
    token = uuid4().hex
    source = "test-" + token
    cfg["redis"]["namespace"] = "empire:test:" + token
    cfg["archive"]["interval_seconds"] = 3600
    manager = build_manager(cfg)
    query = manager.entries["data.news"].plugin
    query.source, query.job_key = source, "news-test"
    try:
        await manager.start("pipeline.ingest")
        await manager.start("data.news")
        await asyncio.sleep(.02)
        ingest = manager.registry.get("ingest.publish")
        archive = manager.registry.get("archive.worker")

        async def publish(ident=101, content="新闻内容", *, batch=None, page=1, updated="2026-09-23 08:00:00",
                          observed=None, flush=True):
            row = normalize_source({"id": ident, "rich_text": content,
                "create_time": "2026-09-23 08:00:00", "update_time": updated,
                "tag": [{"id": "9", "name": "焦点"}], "is_focus": 1})
            batch = batch or uuid4().hex
            event = make_envelope(source=source, dataset="news.flash.page", job_key="news-test",
                run_id=batch, batch_id=batch, business_key=f"{batch}:{page}", payload={"page": page, "rows": [row]})
            if observed:
                event = event.model_copy(update={"observed_at": observed})
            state = await ingest.checkpoint("news-test")
            await ingest.publish_page([event], job_key="news-test", expected_revision=state["revision"], cursor={"page": page})
            if flush:
                await archive.flush()
            return event

        yield manager, publish, query
    finally:
        await manager.stop("pipeline.archive", cascade=True)
        mysql = manager.registry.get("mysql.store")
        def cleanup():
            with mysql.engine.begin() as conn:
                conn.execute(text("DELETE FROM finance_news WHERE source=:source"), {"source": source})
                conn.execute(text("DELETE FROM stock WHERE source=:source"), {"source": source})
        await mysql.read(cleanup)
        store = manager.registry.get("redis.store")
        keys = [key async for key in store.client.scan_iter(match=store.prefix + ":*")]
        if keys:
            assert all(key.startswith("empire:test:" + token + ":") for key in keys)
            await store.client.delete(*keys)
        await manager.shutdown()


async def test_news_retains_history_deduplicates_and_does_not_revert_source_edits(news_db):
    manager, publish, query = news_db
    await publish(content="初版", observed=datetime.now(UTC) - timedelta(minutes=5))
    await publish(content="修订版", updated="2026-09-23 09:00:00")
    await publish(content="旧版迟到", updated="2026-09-23 08:00:00")
    await publish(102, content="第二条新闻")
    listing = await query.list_news()
    assert listing["total"] == 2
    assert next(r for r in listing["rows"] if r["news_id"] == 101)["content"] == "修订版"
    assert (await query.list_news("修订", important=True))["total"] == 1
    assert (await query.list_news("%"))["total"] == 0
    store = manager.registry.get("redis.store")
    assert await store.client.xlen(store.stream) == 0
    assert len(await manager.registry.get("collection.records").list_archives("news-test")) == 4


async def test_news_commit_ack_failure_replays_and_sql_outage_preserves_pending(news_db, monkeypatch):
    manager, publish, query = news_db
    archive = manager.registry.get("archive.worker")
    mysql = manager.registry.get("mysql.store")
    store = manager.registry.get("redis.store")
    original_ack = archive.acknowledge
    async def fail_ack(ids):
        raise ConnectionError("after commit")
    monkeypatch.setattr(archive, "acknowledge", fail_ack)
    with pytest.raises(ConnectionError):
        await publish()
    assert (await query.list_news())["total"] == 1
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive, "acknowledge", original_ack)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    assert (await query.list_news())["total"] == 1

    original = mysql.archive
    async def outage(records):
        raise ConnectionError("SQL offline")
    monkeypatch.setattr(mysql, "archive", outage)
    with pytest.raises(ConnectionError):
        await publish(102)
    assert await store.client.xlen(store.stream) == 1
    assert (await query.list_news())["total"] == 1
    assert not await manager.registry.get("collection.records").list_errors("news-test")
    monkeypatch.setattr(mysql, "archive", original)
    await archive.flush()
    assert (await query.list_news())["total"] == 2


async def test_news_page_failure_does_not_confirm_later_page_in_same_run(news_db, monkeypatch):
    manager, publish, query = news_db
    archive, mysql = manager.registry.get("archive.worker"), manager.registry.get("mysql.store")
    batch = uuid4().hex
    await publish(batch=batch, page=1, flush=False)
    await publish(102, batch=batch, page=2, flush=False)
    original = mysql.archive
    async def fail_first(records):
        if records[0]["normalized"]["page"] == 1:
            raise ConnectionError("first page fails")
        return await original(records)
    monkeypatch.setattr(mysql, "archive", fail_first)
    with pytest.raises(ConnectionError):
        await archive.flush()
    assert await query.page_status(batch, 2) is None
    assert (await query.list_news())["total"] == 0
    monkeypatch.setattr(mysql, "archive", original)
    await archive.flush()
    assert (await query.page_status(batch, 2))["status"] == "complete"
    assert (await query.list_news())["total"] == 2


async def test_incomplete_stock_does_not_block_news_or_replace_stock(news_db):
    manager, publish, query = news_db
    ingest = manager.registry.get("ingest.publish")
    batch = uuid4().hex
    value = make_envelope(source=query.source, dataset="stock.universe.start", job_key="stocks-test",
        run_id=batch, batch_id=batch, business_key=batch, payload={"snapshot_id": batch,
        "started_at": datetime.now(UTC).isoformat(), "expected_count": 1, "page_size": 80, "node": "hs_a"})
    await ingest.publish_page([value], job_key="stocks-test", expected_revision=0, cursor={})
    await publish()
    assert (await query.list_news())["total"] == 1
    store = manager.registry.get("redis.store")
    assert await store.client.xlen(store.stream) == 1
    assert (await store.client.xrange(store.stream))[0][1]["envelope"].find("stock.universe.start") >= 0


async def test_replay_old_run_does_not_regress_archive_progress(news_db):
    manager, publish, query = news_db
    old = await publish(observed=datetime.now(UTC) - timedelta(minutes=5))
    new = await publish(102)
    store = manager.registry.get("redis.store")
    await store.client.xadd(store.stream, {"envelope": old.model_dump_json()})
    await manager.registry.get("archive.worker").flush()
    assert (await query.page_status(new.batch_id, 1))["status"] == "complete"
    assert await query.page_status(old.batch_id, 1) is None


async def test_real_news_pipeline_resumes_checkpoint_after_restart(news_db):
    manager, publish, query = news_db
    value = await publish(flush=False)
    await manager.stop("pipeline.archive", cascade=True)
    await manager.start("pipeline.ingest")
    await manager.registry.get("archive.worker").flush()
    assert (await query.page_status(value.batch_id, 1))["status"] == "complete"
    state = await manager.registry.get("ingest.publish").checkpoint("news-test")
    assert state["revision"] == 1
    assert state["cursor"] == {"page": 1}


async def test_identical_news_and_stale_replays_issue_no_business_dml(news_db):
    manager, publish, query = news_db
    mysql = manager.registry.get("mysql.store")
    initial = datetime.now(UTC) - timedelta(minutes=5)
    await publish(content="初版", observed=initial)
    def stored():
        with mysql.engine.connect() as conn:
            return dict(conn.execute(text("SELECT * FROM finance_news WHERE source=:source"),
                                     {"source": query.source}).mappings().one())
    before = await mysql.read(stored)
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "finance_news" in statement:
            writes.append(statement)
    event.listen(mysql.engine, "before_cursor_execute", capture)
    try:
        await publish(content="初版", observed=initial + timedelta(minutes=1))
        assert not writes
        assert await mysql.read(stored) == before
        await publish(content="修订", observed=initial + timedelta(minutes=2))
        assert len(writes) == 1
        revised = await mysql.read(stored)
        writes.clear()
        await publish(content="旧内容迟到", observed=initial)
        assert not writes and await mysql.read(stored) == revised
        # A new source version is significant even if its displayed text is equal.
        await publish(content="修订", updated="2026-09-23 09:00:00")
        assert len(writes) == 1
    finally:
        event.remove(mysql.engine, "before_cursor_execute", capture)
