"""Guard and whole-set counterexamples for owned names/ST verification tools."""

import asyncio
import copy
import importlib
import json
import os
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest


@pytest.fixture
def capacity(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    return importlib.import_module("event_capacity")


@pytest.mark.parametrize("family", ["name_changes", "st_events"])
def test_capacity_protocol_and_sql_identity_guard(capacity, family):
    p = capacity.protocol(family)
    storage = capacity.EventCapacityStorage(
        dict(host="test", port=13348, user="test"), {}, "a" * 32, "b" * 64, "production", protocol=p
    )
    storage.server_uuid = "private"
    conn = Mock()
    conn.engine.url.database = storage.database
    raw = conn.connection.cursor.return_value
    raw.fetchone.return_value = ("private", storage.database)
    approved = ["ANALYZE TABLE " + p["table"], *("EXPLAIN " + s for s in p["queries"].values())]
    for sql in approved:
        storage.guard(conn, None, sql, (), None, False)
    assert raw.execute.call_count == 4
    for sql in [
        "ANALYZE TABLE stock",
        "EXPLAIN SELECT * FROM stock",
        approved[0] + "; DELETE FROM stock",
        approved[1].replace(p["table"], "empire." + p["table"]),
    ]:
        with pytest.raises(ValueError):
            storage.guard(conn, None, sql, (), None, False)
    for sql in approved:
        with pytest.raises(ValueError):
            storage.guard(conn, None, sql, {"unexpected": 1}, None, False)
        with pytest.raises(ValueError):
            storage.guard(conn, None, sql, (), None, True)
    for identity in [("production", storage.database), ("private", "empire")]:
        raw.fetchone.return_value = identity
        for sql in approved:
            with pytest.raises(ValueError, match="实际实例"):
                storage.guard(conn, None, sql, (), None, False)
    rows = capacity.fixed_rows(p)
    assert len(rows) == 25000 and len({p["contract"].identity(r) for r in rows}) == 25000
    assert {r[1] for r in rows} == {
        "2020-01-01",
        "2020-01-02",
        "2020-01-03",
        "2020-01-04",
        "2020-01-05",
    }


@pytest.mark.parametrize("family", ["name_changes", "st_events"])
def test_equal_count_different_field_or_key_rejected(capacity, family):
    live = importlib.import_module("event_verification")
    c, _, _ = live.components(family)
    rows = capacity.fixed_rows(capacity.protocol(family))[:2]
    wrong = copy.deepcopy(rows)
    wrong[0][3] = "相同条数但内容不同"
    for index in range(3):
        parts = [rows, rows, rows]
        parts[index] = wrong
        with pytest.raises(ValueError, match="完整集合内容"):
            live.check_sets(rows, *parts, c)


@pytest.mark.parametrize("family", ["name_changes", "st_events"])
async def test_cancel_restores_policy_and_instrumentation(capacity, family):
    live = importlib.import_module("event_verification")
    c, _, _ = live.components(family)
    first = next(iter(c.KINDS))
    http = SimpleNamespace(request=AsyncMock())
    ingest = SimpleNamespace(publish_page=AsyncMock())
    collector = SimpleNamespace(
        http=http,
        ingest=ingest,
        checkpoint_revision=AsyncMock(side_effect=asyncio.CancelledError()),
    )
    manager = SimpleNamespace(
        start=AsyncMock(),
        entries={
            (
                "collector.tdx_st_" + first
                if family == "st_events"
                else "collector.tdx_" + first + "_renames"
            ): SimpleNamespace(plugin=collector)
        },
        registry=SimpleNamespace(get=lambda _: None),
    )
    before = (
        live.USE_PROXY.get(),
        live.PROXY_FALLBACK.get(),
        live.ROUTE_COUNTS.get(),
        http.request,
        ingest.publish_page,
    )
    with pytest.raises(asyncio.CancelledError):
        await live.verify_scope(
            manager, {}, SimpleNamespace(event_family=family, proxy_only=True), dict(results={})
        )
    assert before == (
        live.USE_PROXY.get(),
        live.PROXY_FALLBACK.get(),
        live.ROUTE_COUNTS.get(),
        http.request,
        ingest.publish_page,
    )


async def test_paging_cycle_rejected(capacity):
    live = importlib.import_module("event_verification")
    contract = live.components("name_changes")[0]
    query = SimpleNamespace(
        list_events=AsyncMock(
            return_value=dict(rows=[], next=["2020-01-01", "000001.SH", "a" * 64])
        )
    )
    with pytest.raises(ValueError, match="游标重复"):
        await live.full_query(query, contract)


@pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Actual owned SQL/Redis opt-in"
)
@pytest.mark.parametrize("family", ["name_changes", "st_events"])
async def test_owned_event_pipeline_and_cleanup(capacity, family):
    from source_verification import finish

    from empire.__main__ import acquire_instance_lock
    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from tests.prefetch_source import prefetch_http

    live = importlib.import_module("event_verification")
    contract, source, _ = live.components(family)
    sample = importlib.import_module("tests.test_" + family).source
    cfg = load_config()
    settings = json.loads(Path(os.environ["EMPIRE_TEST_MYSQL_SETTINGS"]).read_text("utf-8"))
    storage = capacity.EventCapacityStorage(
        settings,
        cfg["redis"],
        uuid4().hex,
        token_hex(32),
        capacity.read_server_uuid(cfg["mysql"]),
        protocol=capacity.protocol(family),
    )
    manager = lock = None
    report = dict(results={}, cleanup={}, errors=[])
    try:
        lock = acquire_instance_lock()
        storage.create_sql()
        await storage.create_redis()
        storage.seed([], [])
        measured = await asyncio.to_thread(capacity.measure, storage)
        assert measured["correctness"]["row_count"] == 25000
        assert measured["repeat"]["written_count"] == 0
        assert measured["revision"]["written_count"] == 2
        private = copy.deepcopy(cfg)
        private["mysql"], private["redis"]["namespace"] = storage.settings, storage.namespace
        manager = build_manager(private)
        await manager.start("pipeline.ingest")
        await manager.start("infra.http")
        http = manager.registry.get("http.fetch")

        async def response(method, url, **kw):
            value = json.loads(kw["content"])["Params"][0]
            kind = next(k for k, v in contract.KINDS.items() if v[2] == value)
            return httpx.Response(200, json=sample(kind))

        fake = prefetch_http(
            request=AsyncMock(side_effect=response), response_policy=lambda _: None
        )
        http.request = fake.request
        # Retain real resource/prefetch paths; only the remote bytes are the named fixture.
        await live.verify_scope(
            manager, {}, SimpleNamespace(event_family=family, proxy_only=False), report
        )
        assert len(report["results"]) == 2
        assert all(
            x["pipeline_verified"] and x["pending"] == 0 and x["source_query_equal"]
            for x in report["results"].values()
        )
        assert http.request.await_count == 2
        mysql = manager.registry.get("mysql.store")

        def inspect():
            with mysql.engine.connect() as conn:
                for sql in [
                    "ANALYZE TABLE " + storage.protocol["table"],
                    *("EXPLAIN " + q for q in storage.protocol["queries"].values()),
                ]:
                    conn.exec_driver_sql(sql).all()

        await mysql.control(inspect)
    finally:
        await finish(manager, storage, lock, report, Redactor([storage.owner]))
    assert not report["errors"] and all(report["cleanup"].values())
    assert report["remaining"] == dict(sql=False, redis=False)
