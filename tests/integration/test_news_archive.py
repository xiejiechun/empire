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


async def test_fingerprint_hit_skips_sql_and_miss_confirms_then_deletes_queue(news_db, monkeypatch):
    manager, publish, query = news_db
    archive = manager.registry.get("archive.worker")
    mysql = manager.registry.get("mysql.store")
    store = manager.registry.get("redis.store")
    await publish()
    before = await query.list_news()
    original = mysql.archive
    calls = []
    async def capture(records):
        calls.append(records)
        return await original(records)
    monkeypatch.setattr(mysql, "archive", capture)
    await publish()
    assert not calls
    assert await store.client.xlen(store.stream) == 0
    await archive.fingerprints.invalidate("news", query.source)
    await publish()
    assert len(calls) == 1
    archives = await manager.registry.get("collection.records").list_archives("news-test")
    assert len(archives) == 3  # Repeated event ID updates its bounded operational record.
    assert all(record["processed_count"] == 1 for record in archives)
    assert sum(record["written_count"] for record in archives) == 1
    assert await store.client.xlen(store.stream) == 0
    assert await query.list_news() == before
    await publish()
    assert len(calls) == 1


async def test_fingerprint_cache_failure_after_commit_preserves_queue(news_db, monkeypatch):
    manager, publish, query = news_db
    archive = manager.registry.get("archive.worker")
    store = manager.registry.get("redis.store")
    original = archive.fingerprints.put
    async def fail(*args):
        raise ConnectionError("fingerprint write failed")
    monkeypatch.setattr(archive.fingerprints, "put", fail)
    with pytest.raises(ConnectionError):
        await publish()
    assert (await query.list_news())["total"] == 1
    assert await store.client.xlen(store.stream) == 1
    assert not await archive.fingerprints.get("news", query.source, ["101"])
    monkeypatch.setattr(archive.fingerprints, "put", original)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    assert (await query.list_news())["total"] == 1


async def test_cache_bounds_expiry_and_old_sql_version_not_cached(news_db):
    manager, publish, query = news_db
    archive = manager.registry.get("archive.worker")
    store = manager.registry.get("redis.store")
    cache = archive.fingerprints
    cache.limit = 2
    await publish(101, updated="2026-09-23 09:00:00")
    await cache.invalidate("news", query.source)
    await publish(101, content="旧内容", updated="2026-09-23 08:00:00")
    assert not await cache.get("news", query.source, ["101"])
    await publish(101, updated="2026-09-23 09:00:00")
    await publish(102)
    await publish(103)
    keys = cache.keys("news", query.source)
    assert await store.client.hlen(keys[0]) == 2
    assert await store.client.zcard(keys[1]) == 2
    assert 0 < await store.client.ttl(keys[0]) <= cache.ttl
    # Force one entry's deadline into the past without waiting seven days.
    await store.client.zadd(keys[1], {"103": 1})
    assert not await cache.get("news", query.source, ["103"])
    assert not await store.client.hexists(keys[0], "103")
    assert await store.client.xlen(store.stream) == 0


async def test_news_noop_observation_blocks_older_same_source_version(news_db):
    manager, publish, query = news_db
    base = datetime.now(UTC) - timedelta(minutes=10)
    await publish(content="新内容", observed=base)
    await publish(content="新内容", observed=base + timedelta(minutes=3))
    await publish(content="迟到内容", observed=base + timedelta(minutes=2))
    assert (await query.list_news())["rows"][0]["content"] == "新内容"


async def test_mixed_page_only_sends_cache_misses_to_sql(news_db, monkeypatch):
    manager, publish, query = news_db
    archived = await publish(101)
    mysql = manager.registry.get("mysql.store")
    archive = manager.registry.get("archive.worker")
    store = manager.registry.get("redis.store")
    old_row = archived.raw_payload["rows"][0]
    batch = uuid4().hex
    mixed = make_envelope(source=query.source, dataset="news.flash.page", job_key=query.job_key,
        run_id=batch, batch_id=batch, business_key=batch,
        payload={"page": 1, "rows": [{**old_row, "news_id": 102}, old_row]})
    original = mysql.archive
    received = []
    async def capture(records):
        received.extend(row["news_id"] for row in records[0]["normalized"]["rows"])
        return await original(records)
    monkeypatch.setattr(mysql, "archive", capture)
    await store.client.xadd(store.stream, {"envelope": mixed.model_dump_json()})
    await archive.flush()
    assert received == [102]
    assert (await query.list_news())["total"] == 2
    assert await store.client.xlen(store.stream) == 0


async def test_transaction_rollback_cannot_publish_fingerprint(news_db, monkeypatch):
    manager, publish, query = news_db
    archive = manager.registry.get("archive.worker")
    store = manager.registry.get("redis.store")
    original = archive.catalog.write
    def rollback(connection, envelope, data):
        original(connection, envelope, data)
        raise RuntimeError("rollback after business DML")
    monkeypatch.setattr(archive.catalog, "write", rollback)
    with pytest.raises(RuntimeError, match="rollback after"):
        await publish()
    assert (await query.list_news())["total"] == 0
    assert not await archive.fingerprints.get("news", query.source, ["101"])
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive.catalog, "write", original)
    await archive.flush()
    assert (await query.list_news())["total"] == 1
    assert await store.client.xlen(store.stream) == 0


async def test_redis_hit_never_reads_or_updates_mysql_state(news_db, monkeypatch):
    manager, publish, query = news_db
    await publish()
    mysql, store = manager.registry.get("mysql.store"), manager.registry.get("redis.store")
    def state():
        with mysql.engine.connect() as conn:
            return conn.execute(text("SELECT payload,updated_at FROM collection_state WHERE source=:source"),
                                {"source": query.source}).one()
    before = await mysql.control(state)
    async def forbidden(*args, **kwargs):
        raise AssertionError("Redis confirmed hit must not access MySQL")
    monkeypatch.setattr(mysql, "read", forbidden)
    monkeypatch.setattr(mysql, "archive", forbidden)
    await publish()
    assert await store.client.xlen(store.stream) == 0
    monkeypatch.undo()
    assert await mysql.control(state) == before


@pytest.mark.parametrize("damage", ["orphan", "malformed"])
async def test_invalid_redis_proof_falls_back_to_mysql(news_db, monkeypatch, damage):
    manager, publish, query = news_db
    await publish()
    mysql, store = manager.registry.get("mysql.store"), manager.registry.get("redis.store")
    archive = manager.registry.get("archive.worker")
    key, expiry = archive.fingerprints.keys("news", query.source)
    if damage == "orphan":
        await store.client.zrem(expiry, "101")
    else:
        await store.client.hset(key, "101", '{"version":[],"hash":"not-confirmation"}')
    calls = []
    original = mysql.archive
    async def capture(records):
        calls.append(records)
        return await original(records)
    monkeypatch.setattr(mysql, "archive", capture)
    await publish()
    assert len(calls) == 1 and await store.client.xlen(store.stream) == 0
    assert (await query.list_news())["total"] == 1


async def test_state_failure_rolls_back_business_and_progress_recovers_without_redis(news_db):
    manager, publish, query = news_db
    mysql, store = manager.registry.get("mysql.store"), manager.registry.get("redis.store")
    archive = manager.registry.get("archive.worker")
    def fail_state(conn, cursor, statement, params, context, many):
        if statement.lstrip().upper().startswith("INSERT INTO COLLECTION_STATE"):
            raise RuntimeError("injected state write failure")
    event.listen(mysql.engine, "before_cursor_execute", fail_state)
    try:
        with pytest.raises(RuntimeError, match="state write"):
            await publish(batch="state-rollback")
        assert (await query.list_news())["total"] == 0
        assert not await archive.fingerprints.get("news", query.source, ["101"])
        assert await store.client.xlen(store.stream) == 1
    finally:
        event.remove(mysql.engine, "before_cursor_execute", fail_state)
    await archive.flush()
    await store.client.delete(f"{store.prefix}:archive:progress:{query.job_key}")
    assert (await manager.registry.get("archive.confirmation").page_status(
        query.source, query.job_key, query.project_id, "state-rollback", 1))["status"] == "complete"
    await publish(ident=102)
    with mysql.engine.connect() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM collection_state WHERE source=:source"),
                            {"source": query.source}).scalar_one() == 1


@pytest.fixture
async def news_db():
    cfg = copy.deepcopy(load_config())
    token = uuid4().hex
    source = "test-" + token
    cfg["redis"]["namespace"] = "empire:test:" + token
    cfg["archive"]["interval_seconds"] = 3600
    manager = build_manager(cfg)
    query = manager.entries["data.news"].plugin
    query.source, query.job_key, query.project_id = source, "news-test", "news-test"
    try:
        await manager.start("pipeline.ingest")
        await manager.start("data.news")
        await manager.start("infra.archive_confirmation")
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
                conn.execute(text("DELETE FROM collection_state WHERE source=:source"), {"source": source})
                conn.execute(text("DELETE FROM stock WHERE source=:source"), {"source": source})
        await mysql.control(cleanup)
        store = manager.registry.get("redis.store")
        keys = [key async for key in store.client.scan_iter(match=store.prefix + ":*")]
        if keys:
            assert all(key.startswith("empire:test:" + token + ":") for key in keys)
            await store.client.delete(*keys)
        await manager.shutdown()


async def test_queue_publication_wakes_archiver_without_waiting_for_periodic_sweep(news_db):
    manager, publish, query = news_db
    event = await publish(flush=False)
    deadline = asyncio.get_running_loop().time() + 2
    while asyncio.get_running_loop().time() < deadline:
        if await manager.registry.get("archive.confirmation").page_status(
                query.source, query.job_key, query.project_id, event.batch_id, 1):
            break
        await asyncio.sleep(.02)
    status = await manager.registry.get("archive.confirmation").page_status(
        query.source, query.job_key, query.project_id, event.batch_id, 1)
    assert status and status["status"] == "complete"
    assert await manager.registry.get("redis.store").client.xlen(
        manager.registry.get("redis.store").stream) == 0


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
    assert not (await manager.registry.get(
        "collection.records").list_error_summaries("news-test"))["total"]
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
    assert await manager.registry.get("archive.confirmation").page_status(
        query.source, query.job_key, query.project_id, batch, 2) is None
    assert (await query.list_news())["total"] == 0
    monkeypatch.setattr(mysql, "archive", original)
    await archive.flush()
    assert (await manager.registry.get("archive.confirmation").page_status(
        query.source, query.job_key, query.project_id, batch, 2))["status"] == "complete"
    assert (await query.list_news())["total"] == 2


async def test_news_cursor_traversal_is_stable_when_new_rows_arrive(news_db):
    manager, publish, query = news_db
    mysql = manager.registry.get("mysql.store")
    base = datetime(2026, 1, 1, 0, 0)

    def insert_rows(start, count, minute_offset=0):
        rows = [{"source": query.source, "news_id": start + index, "title": f"游标测试 {start + index}",
                 "content": "正文", "published": base + timedelta(minutes=minute_offset + index),
                 "tags": "[]", "url": "https://finance.sina.com.cn/7x24/"}
                for index in range(count)]
        with mysql.engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO finance_news (source,news_id,title,content,published_at,source_updated_at,
                    is_important,tags,url,first_seen_at,version_observed_at)
                VALUES (:source,:news_id,:title,:content,:published,:published,0,:tags,:url,:published,:published)
            """), rows)

    await mysql.control(insert_rows, 1000, 130)
    statements = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "finance_news" in statement:
            statements.append(statement)
    event.listen(mysql.read_engine, "before_cursor_execute", capture)
    first = await query.list_news(limit=25)
    assert first["total"] == 130 and len(first["rows"]) == 25
    assert len(statements) == 2 and sum("COUNT(*)" in item for item in statements) == 1
    assert all(" LIKE " not in item and " OFFSET " not in item for item in statements)
    anchor = first["anchor"]
    seen = [row["news_id"] for row in first["rows"]]
    cursor = first["next_cursor"]
    await mysql.control(insert_rows, 5000, 3, 1000)
    try:
        while cursor:
            statements.clear()
            page = await query.list_news(limit=25, before=cursor, anchor=anchor, include_total=False)
            assert len(statements) == 1 and "COUNT(*)" not in statements[0]
            assert " OFFSET " not in statements[0] and "published_at<" in statements[0]
            assert page["total"] is None and page["anchor"] == anchor
            seen.extend(row["news_id"] for row in page["rows"])
            cursor = page["next_cursor"]
    finally:
        event.remove(mysql.read_engine, "before_cursor_execute", capture)
    assert len(seen) == len(set(seen)) == 130
    assert set(seen) == set(range(1000, 1130))
    refreshed = await query.list_news(limit=25)
    assert refreshed["total"] == 133 and refreshed["rows"][0]["news_id"] == 5002


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
    assert (await manager.registry.get("archive.confirmation").page_status(
        query.source, query.job_key, query.project_id, new.batch_id, 1))["status"] == "complete"
    assert await manager.registry.get("archive.confirmation").page_status(
        query.source, query.job_key, query.project_id, old.batch_id, 1) is None


async def test_real_news_pipeline_resumes_checkpoint_after_restart(news_db):
    manager, publish, query = news_db
    value = await publish(flush=False)
    await manager.stop("pipeline.archive", cascade=True)
    await manager.start("pipeline.ingest")
    await manager.registry.get("archive.worker").flush()
    assert (await manager.registry.get("archive.confirmation").page_status(
        query.source, query.job_key, query.project_id, value.batch_id, 1))["status"] == "complete"
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
    before = await mysql.control(stored)
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "finance_news" in statement:
            writes.append(statement)
    event.listen(mysql.engine, "before_cursor_execute", capture)
    try:
        await publish(content="初版", observed=initial + timedelta(minutes=1))
        assert not writes
        assert await mysql.control(stored) == before
        await publish(content="修订", observed=initial + timedelta(minutes=2))
        assert len(writes) == 1
        revised = await mysql.control(stored)
        writes.clear()
        await publish(content="旧内容迟到", observed=initial)
        assert not writes and await mysql.control(stored) == revised
        # A new source version is significant even if its displayed text is equal.
        await publish(content="修订", updated="2026-09-23 09:00:00")
        assert len(writes) == 1
    finally:
        event.remove(mysql.engine, "before_cursor_execute", capture)
