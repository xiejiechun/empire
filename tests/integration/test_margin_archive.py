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
from empire.features.margin.contract import CONTRACT, DATASET, JOB, pack
from empire.features.margin.dataset import MarginDataset
from empire.features.margin.source import parse
from tests.prefetch_source import prefetch_http
from tests.test_tdx_margin import response

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
        await manager.start("collector.tdx_margin")
        c, q = manager.registry.get("collector.tdx_margin"), manager.registry.get("margin.query")
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
        c.execute(codes=["688256.SH"], baseline_revision=await c.checkpoint_revision()), 30
    )


async def test_formal_roundtrip_duplicate_revision_and_query_boundaries(pipeline):
    manager, c, q, store = pipeline
    await collect(c)
    assert await q.history("688256.SH") == parse(response(), "2026-10-30")
    assert await store.client.xlen(store.stream) == 0
    first = await q.browse(code="688256", limit=1)
    assert first["rows"][0]["financing_repaid"] == 10
    second = await q.browse(code="688256", after=first["next"], limit=1)
    assert second["rows"][0]["first_source_row"] is True
    dml = []

    def track(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            and "margin_" in statement
        ):
            dml.append(statement)

    event.listen(q.mysql.engine, "before_cursor_execute", track)
    try:
        await collect(c)
        assert not dml
        archive = manager.registry.get("archive.worker")
        await archive.fingerprints.invalidate(MarginDataset.FINGERPRINT_NAMESPACE, "tdx")
        await collect(c)
        assert not dml
        body = copy.deepcopy(response())
        body["ResultSets"][0]["Content"][0][4] = 201
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=body)
        await collect(c)
        assert dml
        assert (await q.history("688256.SH"))[0][4] == "201"
        assert await store.client.xlen(store.stream) == 0
        stale = make_envelope(
            source="tdx",
            dataset=DATASET,
            job_key=JOB,
            business_key="688256.SH",
            batch_id="stale",
            run_id="stale",
            schema_version=CONTRACT,
            payload=dict(
                page=1,
                code="688256.SH",
                through="2026-10-28",
                rows=pack(parse(response(), "2026-10-30")),
            ),
        )
        stale = stale.model_copy(update={"observed_at": datetime.now(UTC) - timedelta(days=1)})
        mapping = MarginDataset()
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, "tdx")
        assert (await archive._archive_data(stale, mapping.normalize(stale)))["written_count"] == 0
        assert (await q.history("688256.SH"))[0][4] == "201"
    finally:
        event.remove(q.mysql.engine, "before_cursor_execute", track)


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
    assert not await q.history("688256.SH")
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(mapping, "write", original)
    put = archive.fingerprints.put

    async def fail_redis(*a, **kw):
        raise RuntimeError("injected post-commit failure")

    monkeypatch.setattr(archive.fingerprints, "put", fail_redis)
    with pytest.raises(RuntimeError, match="post-commit"):
        await archive.flush()
    assert len(await q.history("688256.SH")) == 2
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive.fingerprints, "put", put)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    checks = await q.preparation_check("financing", {"codes": ["688256"], "purpose": "analysis"})
    assert next(e for e in checks if e.criterion == "keys").status == "pass"
    # This owned fixture has stopped the archive and invalidates only its cache.
    await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, "tdx")
    with q.mysql.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE margin_daily SET trade_date='2026-10-26' WHERE unified_code='688256.SH' AND trade_date='2026-10-27'"
            )
        )
    checks = await q.preparation_check("financing", {"codes": ["688256"], "purpose": "analysis"})
    assert next(e for e in checks if e.criterion == "keys").status == "fail"
