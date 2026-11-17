"""Private source→normalization→Redis→shared archive→official queries."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from tests.prefetch_source import prefetch_http
from tests.test_tdx_hot_list import CODE, DATE, detail, directory, variant_detail

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
        await manager.start("collector.tdx_hot_list")
        c, q = (
            manager.registry.get("collector.tdx_hot_list"),
            manager.registry.get("hot_list.query"),
        )
        store = manager.registry.get("redis.store")
        c.http = prefetch_http(
            request=AsyncMock(
                side_effect=lambda *a, **k: httpx.Response(
                    200,
                    json=directory()
                    if json.loads(k["content"])["Params"][0] == "0"
                    else detail(shenzhen=True),
                )
            )
        )
        yield manager, c, q, store
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client

            client = create_client(cfg["redis"])
            prefix = cfg["redis"]["namespace"] + ":"
            keys = [k async for k in client.scan_iter(match=prefix + "*")]
            if keys:
                await client.delete(*keys)
            await client.aclose()


async def collect(c, **options):
    return await asyncio.wait_for(
        c.execute(codes=[CODE], baseline_revision=await c.checkpoint_revision(), **options), 30
    )


async def test_tied_source_rank_roundtrip_and_replay(pipeline):
    import copy

    _, c, q, store = pipeline
    body = detail()
    seats = body["ResultSets"][1]
    tied = copy.deepcopy(seats["Content"][1])
    tied[2] = "中国国际金融股份有限公司上海分公司"
    seats["Content"].append(tied)
    seats["Count"] = 3
    c.http.request.side_effect = lambda *a, **k: httpx.Response(
        200, json=directory() if json.loads(k["content"])["Params"][0] == "0" else body
    )
    await collect(c, fresh=True)
    sellers = [r for r in (await q.detail(CODE, DATE))["seats"] if r["side"] == "S"]
    assert len(sellers) == 2
    assert {r["seat_name"] for r in sellers} == {"机构专用", tied[2]}
    assert [r["seat_rank"] for r in sellers] == [1, 1]
    seats["Content"].reverse()
    await collect(c, fresh=True)
    assert [r for r in (await q.detail(CODE, DATE))["seats"] if r["side"] == "S"] == sellers
    assert await store.client.xlen(store.stream) == 0


async def test_reason_variants_roundtrip_and_replay(pipeline):
    from empire.features.hot_list.source import parse_detail

    _, c, q, store = pipeline
    body = variant_detail()
    expected = parse_detail(body)
    c.http.request.side_effect = lambda *a, **k: httpx.Response(
        200, json=directory() if json.loads(k["content"])["Params"][0] == "0" else body
    )
    for _ in range(2):
        await collect(c, fresh=True)
        value = await q.detail(CODE, DATE)
        assert value["detail_status"] == expected["status"]
        assert value["reasons"] == expected["reasons"]
        assert value["seats"] == expected["seats"]
        assert await store.client.xlen(store.stream) == 0
        for result in body["ResultSets"][:2]:
            result["Content"].reverse()


async def test_cold_hot_revision_old_replay_and_source_empty(pipeline):
    manager, c, q, store = pipeline
    await collect(c, fresh=True)
    rows = (await q.browse())["rows"]
    assert len(rows) == 1 and rows[0]["detail_status"] == "present"
    value = await q.detail(CODE, DATE)
    assert len(value["seats"]) == 3 and value["seats"][2]["seat_name"] == "机构专用"
    checks = {
        e.criterion: e.status for e in await q.preparation_check(request={"codes": [CODE[:6]]})
    }
    assert checks["keys"] == checks["fields"] == checks["coverage"] == "pass"
    archive = manager.registry.get("archive.worker")
    dml = []

    def capture(conn, cursor, statement, parameters, context, many):
        if "hot_list_" in statement and statement.lstrip().upper().startswith(
            ("INSERT", "UPDATE", "DELETE")
        ):
            dml.append(statement)

    event.listen(q.mysql.engine, "before_cursor_execute", capture)
    event.listen(q.mysql.archive_engine, "before_cursor_execute", capture)
    try:
        await collect(c, fresh=True)
        assert not dml
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, "tdx")
        await collect(c, fresh=True)
        assert not dml
        c.http.request.side_effect = lambda *a, **k: httpx.Response(
            200,
            json=directory()
            if json.loads(k["content"])["Params"][0] == "0"
            else detail(revised=True),
        )
        await collect(c, fresh=True)
        assert dml
        assert (await q.detail(CODE, DATE))["seats"][0]["buy_amount"] == "30"
        envelope = c.envelope(
            {"batch_id": "replay", "pages": 1},
            "detail",
            CODE,
            DATE,
            __import__("empire.features.hot_list.source", fromlist=["parse_detail"]).parse_detail(
                detail()
            ),
            datetime.now(UTC) - timedelta(days=1),
        )
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, "tdx")
        assert (await archive._archive_data(envelope, q.mapping.normalize(envelope)))[
            "written_count"
        ] == 0
        before = len(dml)
        c.http.request.side_effect = lambda *a, **k: httpx.Response(
            200,
            json=directory()
            if json.loads(k["content"])["Params"][0] == "0"
            else detail(empty=True),
        )
        await collect(c, fresh=True)
        current = await q.detail(CODE, DATE)
        assert (
            current["detail_status"] == "source_empty" and current["seats"][0]["buy_amount"] == "30"
        )
        assert len(dml) > before and await store.client.xlen(store.stream) == 0
        assert (
            next(
                e
                for e in await q.preparation_check(request={"codes": [CODE[:6]]})
                if e.criterion == "fields"
            ).status
            == "fail"
        )
    finally:
        event.remove(q.mysql.engine, "before_cursor_execute", capture)
        event.remove(q.mysql.archive_engine, "before_cursor_execute", capture)


async def test_date_gap_and_sql_commit_then_replay(pipeline):
    manager, c, q, store = pipeline
    await collect(c, fresh=True)
    archive = manager.registry.get("archive.worker")
    envelope = c.envelope(
        {"batch_id": "replay", "pages": 1},
        "detail",
        CODE,
        DATE,
        __import__("empire.features.hot_list.source", fromlist=["parse_detail"]).parse_detail(
            detail(shenzhen=True)
        ),
        datetime.now(UTC),
    )
    await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, "tdx")
    assert (await archive._archive_data(envelope, q.mapping.normalize(envelope)))[
        "written_count"
    ] == 0

    # Private owned SQL tamper plus explicit cache invalidation cannot pass audit.
    def tamper():
        with q.mysql.engine.begin() as conn:
            conn.execute(
                text("DELETE FROM hot_list_seat WHERE unified_code=:code AND seq=2"), {"code": CODE}
            )

    await asyncio.to_thread(tamper)
    checks = {
        e.criterion: e.status for e in await q.preparation_check(request={"codes": [CODE[:6]]})
    }
    assert checks["keys"] == "fail"


async def test_failed_transaction_retains_queue_and_post_commit_replay(pipeline, monkeypatch):
    manager, c, q, store = pipeline
    from empire.features.hot_list.contract import DATASET

    archive = manager.registry.get("archive.worker")
    await archive.stop()
    archive.stop_event.clear()
    task = asyncio.create_task(collect(c, fresh=True))
    async with asyncio.timeout(5):
        while await store.client.xlen(store.stream) != 4:
            await asyncio.sleep(0.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    mapping = next(
        d.mapping
        for d in manager.registry.get("dataset.catalog").contributions
        if DATASET in d.mapping.DATASETS
    )
    original = mapping.write

    def fail(conn, envelope, data):
        result = original(conn, envelope, data)
        if data["mode"] == "detail":
            raise RuntimeError("injected detail transaction failure")
        return result

    monkeypatch.setattr(mapping, "write", fail)

    async def flush_all():
        # Each flush is a bounded scheduling quantum, not a drain operation.
        async with asyncio.timeout(5):
            while await store.client.xlen(store.stream):
                await archive.flush()

    with pytest.raises(RuntimeError, match="transaction failure"):
        await flush_all()
    current = await q.detail(CODE, DATE)
    assert current["detail_status"] == "pending" and not current["seats"]
    assert await store.client.xlen(store.stream) == 3
    monkeypatch.setattr(mapping, "write", original)
    put = archive.fingerprints.put

    async def fail_redis(*args, **kwargs):
        raise RuntimeError("injected post-commit failure")

    monkeypatch.setattr(archive.fingerprints, "put", fail_redis)
    with pytest.raises(RuntimeError, match="post-commit"):
        await flush_all()
    assert (await q.detail(CODE, DATE))["detail_status"] == "present"
    assert await store.client.xlen(store.stream) == 3
    monkeypatch.setattr(archive.fingerprints, "put", put)
    await flush_all()
    assert await store.client.xlen(store.stream) == 0
    result = await collect(c)
    assert result["phase"] == "complete"


@pytest.mark.parametrize("failed_mode", ["0", "1"])
async def test_query_timeout_exhaustion_preserves_cursor_and_resumes(pipeline, monkeypatch, failed_mode):
    from empire.features.hot_list.source import parse_detail
    from empire.plugins.infra.http import HttpService
    from tests.test_hot_list_timeout import GROUPS, TIMEOUT
    from tests.test_http import ErrorRecorder, MemoryPermits

    _, c, q, store = pipeline
    failing, attempts = True, []

    def respond(request):
        mode = json.loads(request.content)["Params"][0]
        attempts.append(mode)
        return httpx.Response(200, json=TIMEOUT if failing and mode == failed_mode else
                              directory() if mode == "0" else detail())

    service = HttpService(MemoryPermits(), "timeout-test", GROUPS, records=ErrorRecorder(),
                          transport=httpx.MockTransport(respond))
    c.http, c.request_retries = service, 2
    monkeypatch.setattr("empire.plugins.infra.http.retry_delay", lambda attempt: 0)
    try:
        with pytest.raises(ValueError, match="cache语句执行超时"):
            await collect(c, fresh=True)
        assert attempts.count(failed_mode) == 3
        checkpoint = await c.ingest.checkpoint(c.job_key)
        cursor = checkpoint["cursor"]
        assert not cursor or (cursor["index"] == 0 and cursor["last_date"] == "")
        current = await q.detail(CODE, DATE)
        assert current is None or not current["seats"]
        batch = cursor.get("batch_id")
        failing = False
        result = await collect(c)
        assert result["phase"] == "complete"
        if batch:
            assert result["batch_id"] == batch
        value = await q.detail(CODE, DATE)
        expected = parse_detail(detail())
        assert value["reasons"] == expected["reasons"]
        assert value["seats"] == expected["seats"]
        assert value["detail_status"] == expected["status"]
        assert await store.client.xlen(store.stream) == 0
        assert service.buffer_budget.used == 0
    finally:
        await service.close()
