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
from empire.features.industry_margin.contract import CONTRACT, DATASET, JOB
from empire.features.industry_margin.dataset import IndustryMarginDataset
from empire.features.industry_margin.source import parse
from tests.prefetch_source import prefetch_http
from tests.test_industry_margin import response

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
        await manager.start("collector.tdx_industry_margin")
        c, q = (
            manager.registry.get("collector.tdx_industry_margin"),
            manager.registry.get("industry_margin.query"),
        )
        store = manager.registry.get("redis.store")
        import json

        def fetch(*a, **kw):
            params = json.loads(kw["content"])["Params"]
            return httpx.Response(
                200,
                json=response()
                if params[0] == "1"
                else {
                    "ErrorCode": 0,
                    "ResultSets": [{"ColName": ["mxt"], "Count": 1, "Content": [["20261028"]]}],
                },
            )

        c.http = prefetch_http(request=AsyncMock(side_effect=fetch))
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
        c.execute(
            start="2016-01-04", end="2016-01-04", baseline_revision=await c.checkpoint_revision()
        ),
        30,
    )


async def test_source_negative_preserved_with_quality_failure(pipeline):
    manager, c, q, store = pipeline
    original = c.http.request.side_effect

    def negative(*args, **kwargs):
        result = original(*args, **kwargs)
        body = result.json()
        if body["ResultSets"][0]["ColName"] != ["mxt"]:
            body["ResultSets"][0]["Content"][0][5] = -1.6449
        return httpx.Response(200, json=body)

    c.http.request.side_effect = negative
    await collect(c)
    assert (await q.history("2016-01-04"))[0][6] == "-1.6449"
    checks = await q.preparation_check(
        dict(start="2016-01-04", end="2016-01-04", purpose="analysis")
    )
    assert next(e for e in checks if e.criterion == "quality").status == "fail"
    assert next(e for e in checks if e.criterion == "coverage").status == "pass"
    assert await store.client.xlen(store.stream) == 0


async def test_pipeline_hot_cold_revision_stale_and_empty_rejection(pipeline):
    manager, c, q, store = pipeline
    await collect(c)
    assert await q.history("2016-01-04") == parse(response())
    assert await store.client.xlen(store.stream) == 0
    first = await q.browse(start="2016-01-04", end="2016-01-04", limit=1)
    second = await q.browse(after=first["next"], limit=1)
    assert len(first["rows"]) == len(second["rows"]) == 1
    assert first["rows"][0]["industry_name"] != second["rows"][0]["industry_name"]
    dml = []

    def track(conn, cursor, statement, parameters, context, executemany):
        if (
            statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))
            and "industry_margin_" in statement
        ):
            dml.append(statement)

    event.listen(q.mysql.engine, "before_cursor_execute", track)
    event.listen(q.mysql.archive_engine, "before_cursor_execute", track)
    archive = manager.registry.get("archive.worker")
    mapping = IndustryMarginDataset()
    try:
        await collect(c)
        assert not dml
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, "tdx")
        await collect(c)
        assert not dml
        body = copy.deepcopy(response())
        body["ResultSets"][0]["Content"][0][1] = 201
        original = c.http.request.side_effect

        def revised(*a, **kw):
            import json

            return (
                httpx.Response(200, json=body)
                if json.loads(kw["content"])["Params"][0] == "1"
                else original(*a, **kw)
            )

        c.http.request.side_effect = revised
        await collect(c)
        assert dml and (await q.history("2016-01-04"))[0][2] == "201"
        assert await store.client.xlen(store.stream) == 0
        stale = make_envelope(
            source="tdx",
            dataset=DATASET,
            job_key=JOB,
            business_key="2016-01-04",
            batch_id="stale",
            run_id="stale",
            schema_version=CONTRACT,
            payload=dict(
                page=1, date="2016-01-04", rows=parse(response()), source_latest="2026-10-28"
            ),
        )
        stale = stale.model_copy(update={"observed_at": datetime.now(UTC) - timedelta(days=1)})
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, "tdx")
        assert (await archive._archive_data(stale, mapping.normalize(stale)))["written_count"] == 0
        empty = stale.model_copy(
            update={
                "observed_at": datetime.now(UTC),
                "raw_payload": dict(page=1, date="2016-01-04", rows=[], source_latest="2026-10-28"),
            }
        )
        with pytest.raises(ValueError, match="空响应"):
            await archive._archive_data(empty, mapping.normalize(empty))
        assert (await q.history("2016-01-04"))[0][2] == "201"
    finally:
        event.remove(q.mysql.engine, "before_cursor_execute", track)
        event.remove(q.mysql.archive_engine, "before_cursor_execute", track)


async def test_transaction_failure_commit_replay_content_corruption(pipeline, monkeypatch):
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
        raise RuntimeError("transaction failure")

    monkeypatch.setattr(mapping, "write", fail)
    with pytest.raises(RuntimeError, match="transaction failure"):
        await archive.flush()
    assert not await q.history("2016-01-04") and await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(mapping, "write", original)
    put = archive.fingerprints.put

    async def fail_redis(*a, **kw):
        raise RuntimeError("post-commit failure")

    monkeypatch.setattr(archive.fingerprints, "put", fail_redis)
    with pytest.raises(RuntimeError, match="post-commit"):
        await archive.flush()
    assert len(await q.history("2016-01-04")) == 2 and await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive.fingerprints, "put", put)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    await collect(c)  # Finish the interrupted round's already-published checkpoint.
    scope = dict(start="2016-01-04", end="2016-01-04", purpose="analysis")
    assert all(e.status == "pass" or not e.blocking for e in await q.preparation_check(scope))
    await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, "tdx")
    with q.mysql.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE industry_margin_daily SET industry_name='同数异集' WHERE industry_name='煤炭'"
            )
        )
    assert (
        next(e for e in await q.preparation_check(scope) if e.criterion == "keys").status == "fail"
    )
    # Fresh source snapshot restores the exact keys, not just row count.
    task = asyncio.create_task(collect(c))
    async with asyncio.timeout(5):
        while await store.client.xlen(store.stream) != 1:
            await asyncio.sleep(0.01)
    await archive.flush()
    await task
    assert await q.history("2016-01-04") == parse(response())
