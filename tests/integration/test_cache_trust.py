"""Corrupt Redis proof must reach SQL; failed SQL never acknowledges good data."""
import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from test_calendar_archive import calendar_db as calendar_db
from test_news_archive import news_db as news_db
from test_stock_archive import ROWS
from test_stock_archive import stock_database as stock_database

from empire.contracts.data import make_envelope

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly")]
DAMAGE = ["text", "dimension", "timezone", "future", "precision", "hash", "orphan", "expired", "infinite"]


async def check_recovery(manager, query, namespace, ident, publish, damage, monkeypatch):
    await publish()
    archive = manager.registry.get("archive.worker")
    mysql = manager.registry.get("mysql.store")
    store = manager.registry.get("redis.store")
    key, expiry = archive.fingerprints.keys(namespace, query.source)
    proof = json.loads(await store.client.hget(key, ident))
    observed_index = 1 if namespace == "news" else 0
    if damage == "text":
        proof["version"] = ["not-a-timestamp"]
    elif damage == "dimension":
        proof["version"].append("unexpected")
    elif damage == "timezone":
        old = proof["version"][observed_index]
        proof["version"][observed_index] = old + "+00:00" if namespace == "stocks" else old[:-6]
    elif damage == "future":
        value = datetime.now(UTC) + timedelta(days=1)
        if namespace == "stocks":
            value = value.replace(tzinfo=None)
        proof["version"][observed_index] = value.isoformat(timespec="microseconds")
    elif damage == "source-future":
        proof["version"][0] = "9999-12-31T00:00:00.000000+00:00"
    elif damage == "precision":
        old = datetime.fromisoformat(proof["version"][observed_index])
        proof["version"][observed_index] = old.isoformat(timespec="seconds")
    elif damage == "hash":
        proof["hash"] = "not-confirmed"
    elif damage == "orphan":
        await store.client.zrem(expiry, ident)
    elif damage in ("expired", "infinite"):
        await store.client.zadd(expiry, {ident: 1 if damage == "expired" else float("inf")})
    await store.client.hset(key, ident, json.dumps(proof))
    assert not await archive.fingerprints.get(namespace, query.source, [ident])
    # Isolate the proof path: changed business data must not be labelled stale.
    original, calls = mysql.archive, []
    async def offline(records):
        calls.append(records)
        raise ConnectionError("SQL unavailable while validating proof")
    monkeypatch.setattr(mysql, "archive", offline)
    with pytest.raises(ConnectionError, match="validating proof"):
        await publish(changed=True)
    assert calls and await store.client.xlen(store.stream) > 0
    monkeypatch.setattr(mysql, "archive", original)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    assert await archive.fingerprints.get(namespace, query.source, [ident])


@pytest.mark.parametrize("damage", [*DAMAGE, "source-future"])
async def test_news_invalid_proof_retains_data_until_sql_confirms(news_db, damage, monkeypatch):
    manager, publish, query = news_db
    async def send(changed=False):
        await publish(content="有效修订" if changed else "新闻内容")
    await check_recovery(manager, query, "news", "101", send, damage, monkeypatch)
    assert (await query.list_news())["rows"][0]["content"] == "有效修订"


async def test_source_clock_anomaly_still_archives_but_cannot_become_cache_evidence(news_db, monkeypatch):
    manager, publish, query = news_db
    await publish()
    archive, store = manager.registry.get("archive.worker"), manager.registry.get("redis.store")
    await publish(content="来源时钟超前", updated="2099-12-31 00:00:00")
    assert (await query.list_news())["rows"][0]["content"] == "来源时钟超前"
    assert not await archive.fingerprints.get("news", query.source, ["101"])
    assert await store.client.xlen(store.stream) == 0
    mysql, calls = manager.registry.get("mysql.store"), []
    original = mysql.archive
    async def capture(records):
        calls.append(records)
        return await original(records)
    monkeypatch.setattr(mysql, "archive", capture)
    await publish(content="正常来源时间的迟到响应")
    assert calls and (await query.list_news())["rows"][0]["content"] == "来源时钟超前"
    assert await store.client.xlen(store.stream) == 0


@pytest.mark.parametrize("damage", DAMAGE)
async def test_calendar_invalid_proof_retains_data_until_sql_confirms(calendar_db, damage, monkeypatch):
    manager, query, publish = calendar_db
    async def send(changed=False):
        await publish(trading=not changed)
    await check_recovery(manager, query, "calendar", "2027-01", send, damage, monkeypatch)
    assert all(not row["is_trade"] for row in (await query.month("2027-01"))["rows"])


@pytest.mark.parametrize("damage", DAMAGE)
async def test_stock_invalid_proof_retains_data_until_sql_confirms(stock_database, damage, monkeypatch):
    snapshot, _, query, manager = stock_database
    store = manager.registry.get("redis.store")
    archive = manager.registry.get("archive.worker")
    async def send(changed=False):
        batch = snapshot()
        rows = [{**ROWS[0], "name": "有效修订"}, ROWS[1]] if changed else ROWS
        for kind, payload in (("page", {"page": 1, "rows": rows}),
                              ("complete", {"pages": 1, "collected": 2, "count_after": 2, "terminal_rows": []})):
            value = make_envelope(source=query.source, dataset=f"stock.universe.{kind}",
                job_key=query.job_key, run_id=batch["snapshot_id"], batch_id=batch["snapshot_id"],
                business_key=f"{batch['snapshot_id']}:{kind}", payload={**batch, **payload})
            await store.client.xadd(store.stream, {"envelope": value.model_dump_json()})
        await archive.flush()
    await check_recovery(manager, query, "stocks", "current", send, damage, monkeypatch)
    assert (await query.list_stocks())["rows"][0]["name"] == "有效修订"


@pytest.mark.parametrize("marker", ["bad-json", "future", "different-batch", "wrong-type"])
async def test_stock_committed_progress_cannot_authorize_queue_removal(stock_database, marker, monkeypatch):
    snapshot, publish, query, manager = stock_database
    archive, store = manager.registry.get("archive.worker"), manager.registry.get("redis.store")
    initial = snapshot()
    await publish("page", initial, page=1, rows=ROWS)
    await publish("complete", initial, pages=1, collected=2, count_after=2, terminal_rows=[])
    key = f"{store.prefix}:stocks:committed:{query.source}"
    value = json.loads(await store.client.get(key))
    if marker == "future":
        value["started_at"] = "9999-12-31T00:00:00"
    elif marker == "different-batch":
        value["snapshot_id"] = "not-a-valid-batch"
    elif marker == "wrong-type":
        value = []
    await store.client.set(key, "{" if marker == "bad-json" else json.dumps(value))
    await archive.fingerprints.invalidate("stocks", query.source)
    next_batch = snapshot()
    await publish("page", next_batch, page=1, rows=[{**ROWS[0], "name": "新数据"}, ROWS[1]])
    assert await store.client.xlen(store.stream) == 1
    await publish("complete", next_batch, pages=1, collected=2, count_after=2, terminal_rows=[])
    assert (await query.list_stocks())["rows"][0]["name"] == "新数据"
    assert await store.client.xlen(store.stream) == 0


@pytest.mark.parametrize("cursor", [
    "{", "[]", '{"snapshot_id":"a","started_at":"not-a-time"}',
    json.dumps({"snapshot_id": "f" * 32, "started_at": "9999-01-01T00:00:00+00:00"}),
    json.dumps({"snapshot_id": "f" * 32, "started_at": "2026-09-26T00:00:00"}),
])
async def test_damaged_checkpoint_cannot_discard_incomplete_stock_pages(stock_database, cursor):
    snapshot, publish, _, manager = stock_database
    store = manager.registry.get("redis.store")
    await publish("page", snapshot(), page=1, rows=ROWS)
    await store.client.hset(f"{store.prefix}:checkpoint:test", "cursor", cursor)
    await manager.registry.get("archive.worker").flush()
    assert await store.client.xlen(store.stream) == 1
