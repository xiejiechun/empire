import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.market_margin.contract import CONTRACT, DATASET, JOB, pack
from empire.features.market_margin.dataset import MarketMarginDataset
from empire.features.market_margin.source import parse
from tests.prefetch_source import prefetch_http
from tests.test_market_margin import response

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Private SQL/Redis opt-in"
    ),
]


@pytest.fixture
async def pipeline():
    cfg = load_config()
    manager = build_manager(cfg)
    store = None
    try:
        await manager.start("collector.ths_market_margin")
        c, q = (
            manager.registry.get("collector.ths_market_margin"),
            manager.registry.get("market_margin.query"),
        )
        store = manager.registry.get("redis.store")
        c.http = prefetch_http(
            request=AsyncMock(side_effect=lambda *a, **kw: httpx.Response(200, json=response()))
        )
        yield manager, c, q, store
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client

            client = create_client(cfg["redis"])
            keys = [k async for k in client.scan_iter(match=cfg["redis"]["namespace"] + ":*")]
            if keys:
                await client.delete(*keys)
            await client.aclose()


async def collect(c):
    return await asyncio.wait_for(
        c.execute(markets=["99"], baseline_revision=await c.checkpoint_revision()), 30
    )


async def test_formal_roundtrip_duplicate_revision_and_query_boundaries(pipeline):
    manager, c, q, store = pipeline
    await collect(c)
    assert await q.history("99") == parse(response(), "2026-10-30", "99")
    assert await store.client.xlen(store.stream) == 0
    first = await q.browse(search="99", limit=1)
    assert first["rows"][0]["total_balance"] == 120
    second = await q.browse(search="99", after=first["next"], limit=1)
    assert second["rows"][0]["trade_date"] == "2010-03-31"
    dml = []

    def track(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            and "margin_" in statement
        ):
            dml.append(statement)

    event.listen(q.mysql.engine, "before_cursor_execute", track)
    event.listen(q.mysql.archive_engine, "before_cursor_execute", track)
    try:
        await collect(c)
        assert not dml
        archive = manager.registry.get("archive.worker")
        await archive.fingerprints.invalidate(MarketMarginDataset.FINGERPRINT_NAMESPACE, "ths")
        await collect(c)
        assert not dml
        body = copy.deepcopy(response())
        body["data"]["item"][0]["rzye"] = 201
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=body)
        await collect(c)
        assert dml
        assert (await q.history("99"))[0][1] == "201"
        assert await store.client.xlen(store.stream) == 0
        stale = make_envelope(
            source="ths",
            dataset=DATASET,
            job_key=JOB,
            business_key="99",
            batch_id="stale",
            run_id="stale",
            schema_version=CONTRACT,
            payload=dict(
                page=1,
                code="99",
                through="2026-10-28",
                rows=pack(parse(response(), "2026-10-30", "99")),
            ),
        )
        stale = stale.model_copy(update={"observed_at": datetime.now(UTC) - timedelta(days=1)})
        mapping = MarketMarginDataset()
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, "ths")
        assert (await archive._archive_data(stale, mapping.normalize(stale)))["written_count"] == 0
        assert (await q.history("99"))[0][1] == "201"
    finally:
        event.remove(q.mysql.engine, "before_cursor_execute", track)
        event.remove(q.mysql.archive_engine, "before_cursor_execute", track)


async def test_failure_retention_commit_replay_and_same_count_corruption(pipeline, monkeypatch):
    manager, c, q, store = pipeline
    archive = manager.registry.get("archive.worker")
    await archive.stop()
    archive.stop_event.clear()
    task = asyncio.create_task(collect(c))
    async with asyncio.timeout(5):
        while await store.client.xlen(store.stream) != 1:
            await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    mapping = next(
        x.mapping
        for x in manager.registry.get("dataset.catalog").contributions
        if DATASET in x.mapping.DATASETS
    )
    original = mapping.write

    def fail(conn, envelope, data):
        original(conn, envelope, data)
        raise RuntimeError("injected transaction failure")

    monkeypatch.setattr(mapping, "write", fail)
    with pytest.raises(RuntimeError, match="transaction failure"):
        await archive.flush()
    assert not await q.history("99")
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(mapping, "write", original)
    put = archive.fingerprints.put

    async def fail_redis(*a, **kw):
        raise RuntimeError("injected post-commit failure")

    monkeypatch.setattr(archive.fingerprints, "put", fail_redis)
    with pytest.raises(RuntimeError, match="post-commit"):
        await archive.flush()
    assert len(await q.history("99")) == 2
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive.fingerprints, "put", put)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    checks = await q.preparation_check("market_financing", {"purpose": "analysis"})
    assert (
        next(e for e in checks if e.criterion == "keys").status == "fail"
    )  # other three markets absent
    # This owned fixture has stopped the archive and invalidates only its cache.
    await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, "ths")
    with q.mysql.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE market_margin_daily SET trade_date='2010-04-02' WHERE market_code='99' AND trade_date='2010-04-01'"
            )
        )
    checks = await q.preparation_check("market_financing", {"purpose": "analysis"})
    assert next(e for e in checks if e.criterion == "keys").status == "fail"


async def test_all_markets_archive_decoupled_resume_and_cost(pipeline):
    manager, c, q, store = pipeline
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(
        200, json=response(url.rstrip("/").split("/")[-1])
    )
    archive = manager.registry.get("archive.worker")
    await archive.stop()
    archive.stop_event.clear()
    task = asyncio.create_task(c.execute(baseline_revision=await c.checkpoint_revision()))
    async with asyncio.timeout(8):
        while await store.client.xlen(store.stream) != 4:
            await asyncio.sleep(0.01)
    assert c.http.request.call_count == 4  # all published without awaiting prior archive
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await archive.flush()
    baseline = await c.checkpoint_revision()
    done = await c.execute(baseline_revision=baseline)
    assert done["phase"] == "complete"
    assert c.http.request.call_count == 4  # awaiting_archive resume does not redownload
    assert await store.client.xlen(store.stream) == 0
    checks = await q.preparation_check("market_financing", {"purpose": "analysis"})
    assert all(e.status == "pass" or not e.blocking for e in checks)
    # New round with live archive: four full-source requests is the declared exception.
    await archive.start(manager.entries["pipeline.archive"].context)
    try:
        await c.execute(baseline_revision=await c.checkpoint_revision())
        assert c.http.request.call_count == 8

        def added(method, url, **kw):
            b = response(url.rstrip("/").split("/")[-1])
            from datetime import date

            b["data"]["date"].append(
                (date.fromisoformat(b["data"]["date"][-1]) + timedelta(days=1)).isoformat()
            )
            b["data"]["item"].append(dict(b["data"]["item"][-1]))
            return httpx.Response(200, json=b)

        c.http.request.side_effect = added
        await c.execute(baseline_revision=await c.checkpoint_revision())
        assert c.http.request.call_count == 12
        assert len(await q.history("99")) == 3
        # Owned fixture only: lose temporary checkpoint, retain SQL and verify recovery.
        checkpoint = await c.ingest.checkpoint(JOB)
        await c.ingest.advance_checkpoint(
            job_key=JOB, expected_revision=checkpoint["revision"], cursor={}
        )
        await c.execute(baseline_revision=await c.checkpoint_revision())
        assert c.http.request.call_count == 16
        assert await store.client.xlen(store.stream) == 0
    finally:
        await archive.stop()
