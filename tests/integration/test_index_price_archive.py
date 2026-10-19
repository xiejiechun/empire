"""Private-schema source → Redis → archive → formal query and replay evidence."""

import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.index_prices.contract import JOB
from empire.features.index_prices.dataset import FINGERPRINT_NAMESPACE
from tests.test_ths_index_prices import CODE, ROWS, envelope
from tests.test_ths_index_prices import collector as fake_collector

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Explicit private database"
    ),
]


@pytest.fixture
async def prices():
    cfg = copy.deepcopy(load_config())
    cfg["redis"]["namespace"] = "empire:test:" + uuid4().hex
    manager = build_manager(cfg)
    store = None
    try:
        await manager.start("collector.ths_index_prices")
        c, q, store = (
            manager.registry.get(k)
            for k in ("collector.ths_index_prices", "index.prices.query", "redis.store")
        )
        c.http = fake_collector().http
        c.session = SimpleNamespace(headers=lambda _: {})

        def seed():
            with q.mysql.engine.begin() as conn:
                conn.execute(
                    text(
                        "INSERT INTO stock_index(index_code,name,source_group) VALUES(:code,:name,:group)"
                    ),
                    dict(code=CODE, name="红利100", group="测试"),
                )

        await q.mysql.control(seed)

        async def publish(e):
            state = await c.ingest.checkpoint(JOB)
            await c.ingest.publish_page(
                [e], job_key=JOB, expected_revision=state["revision"], cursor=dict(test=True)
            )
            await manager.registry.get("archive.worker").flush()

        yield manager, c, q, store, publish
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client

            client = create_client(cfg["redis"])
            keys = [k async for k in client.scan_iter(match=cfg["redis"]["namespace"] + ":*")]
            if keys:
                assert all(k.startswith(cfg["redis"]["namespace"] + ":") for k in keys)
                await client.delete(*keys)
            await client.aclose()


async def test_source_formal_query_year_proof_and_pagination(prices):
    _, c, q, store, _ = prices
    result = await asyncio.wait_for(c.execute(), 15)
    assert result["collected"] == 3
    first = await q.browse(CODE, limit=1)
    assert first["rows"][0]["trade_date"].isoformat() == ROWS[0][0] and first["next"]
    second = await q.browse(CODE, after=first["next"])
    assert len(second["rows"]) == 2 and second["rows"][-1]["amount"] == 3000
    assert all(v["complete"] for v in (await q.year_heads(CODE)).values())
    checks = await q.preparation_check(dict(index_codes=[CODE]))
    assert next(e for e in checks if e.criterion == "coverage").status == "pass"
    assert await store.client.xlen(store.stream) == 0
    # Redis checkpoint loss uses SQL yearly proofs and makes only one last request.
    from empire.features.index_prices.collector import ThsIndexPriceCollector

    await c.ingest.redis.client.delete(c.ingest._checkpoint_key(JOB))
    c.http.request.reset_mock()
    await ThsIndexPriceCollector.execute(c)
    assert c.http.request.await_count == 1


@pytest.mark.parametrize("annual_values", [
    [None, None, None, "12.9", "0", None],
    ["12", "14", "11", "12.9", "200", "2000"],
])
@pytest.mark.parametrize("observed_day", [2, 3])
async def test_latest_resolution_archives_verified_recent_values(prices, annual_values, observed_day):
    from empire.core.time import CHINA
    from empire.features.index_prices.source import annual, recent
    from tests.test_ths_index_prices import source

    _, c, q, store, publish = prices
    await c.execute()
    now = datetime(2026, 1, observed_day, 16, tzinfo=CHINA)
    snapshot = recent(source(), CODE, now)
    rows = annual(source(2026, [["2026-01-02", *annual_values]]),
                  CODE, 2026, snapshot, now)
    e = envelope(rows=rows, year=2026, page=4)
    from empire.contracts.data import make_envelope
    e = make_envelope(source=e.source, dataset=e.dataset, business_key=e.business_key,
                      job_key=e.job_key, batch_id=e.batch_id, run_id=e.run_id,
                      payload={**e.raw_payload, "source_count": 1})
    await publish(e)
    result = await q.browse(CODE, start="2026-01-02", end="2026-01-02")
    assert len(result["rows"]) == 1
    assert str(result["rows"][0]["close"]) == "13.000000"
    assert result["rows"][0]["volume"] == 300 and result["rows"][0]["amount"] == 3000
    assert (await q.year_heads(CODE))["2026"]["complete"]
    assert await store.client.xlen(store.stream) == 0


async def test_hot_cold_duplicate_revision_late_response_no_business_dml(prices):
    m, c, q, store, publish = prices
    await c.execute()
    archive = m.registry.get("archive.worker")
    await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, "ths")
    writes = []

    def capture(conn, cursor, sql, params, context, many):
        if (
            "index_daily_price" in sql or "index_price_year" in sql
        ) and sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)

    event.listen(q.mysql.engine, "before_cursor_execute", capture)
    try:
        now = datetime.now(UTC)
        base = envelope().model_copy(update={"observed_at": now})
        await publish(base)
        assert writes == []
        await publish(base.model_copy(update={"observed_at": now + timedelta(seconds=1)}))
        assert writes == [] and await store.client.xlen(store.stream) == 0
        revised = copy.deepcopy(ROWS[:2])
        revised[1][4] = "12.5"
        changed = envelope(revised).model_copy(update={"observed_at": now + timedelta(seconds=2)})
        await publish(changed)
        count = len(writes)
        assert count == 2 and (await q.browse(CODE))["rows"][1]["close"] == 12.5
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, "ths")
        await publish(base)
        assert len(writes) == count and (await q.browse(CODE))["rows"][1]["close"] == 12.5
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, "before_cursor_execute", capture)


async def test_partial_cannot_prove_missing_history_and_old_fields_are_filled(prices):
    _, _, q, store, publish = prices
    now = datetime.now(UTC)
    await publish(envelope([ROWS[1]], mode="recent").model_copy(update={"observed_at": now}))
    assert not (await q.year_heads(CODE))["2025"]["complete"]
    await publish(envelope().model_copy(update={"observed_at": now + timedelta(seconds=1)}))
    assert (await q.year_heads(CODE))["2025"]["complete"]
    assert len((await q.browse(CODE))["rows"]) == 2 and await store.client.xlen(store.stream) == 0


@pytest.mark.parametrize("missing_prices", [False, True, "amount", "negative"])
async def test_sql_commit_before_redis_confirmation_replays_without_writes(prices, monkeypatch, missing_prices):
    m, _, q, store, publish = prices
    archive = m.registry.get("archive.worker")
    original = archive.fingerprints.put

    async def fail(*args, **kwargs):
        raise RuntimeError("Redis confirmation unavailable")

    monkeypatch.setattr(archive.fingerprints, "put", fail)
    values = copy.deepcopy(ROWS[:2])
    if missing_prices == "negative":
        values[0][5:7] = ["-100", "-798120910000"]
    elif missing_prices == "amount":
        values[0][6] = None
    elif missing_prices:
        for row in values:
            row[1:4] = [None, None, None]
    with pytest.raises(RuntimeError):
        await publish(envelope(values))
    assert len((await q.browse(CODE))["rows"]) == 2 and await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive.fingerprints, "put", original)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    assert len((await q.browse(CODE))["rows"]) == 2


async def test_source_missing_amount_archive_scope_replay_and_fill(prices):
    from tests.test_ths_index_prices import source
    manager, c, q, store, publish = prices
    changed = copy.deepcopy(ROWS)
    changed[0][6] = None

    def response(method, address, **kw):
        unit = address.rsplit("/", 1)[1].split(".")[0]
        body = source(rows=changed) if unit == "last" else source(unit, [r for r in changed if r[0][:4] == unit])
        return httpx.Response(200, content=body.encode())

    c.http.request.side_effect = response
    await c.execute()
    assert (await q.browse(CODE))["rows"][0]["amount"] is None
    assert (await q.year_heads(CODE))["2025"]["complete"]
    checks = await q.preparation_check(dict(index_codes=[CODE]))
    quality = next(e for e in checks if e.criterion == "quality")
    assert quality.status == "pass" and "1条来源缺少成交额" in quality.measured
    clean_scope = await q.preparation_check(dict(index_codes=[CODE], start="2025-12-31", end="2025-12-31"))
    assert "0条来源缺少成交额" in next(e for e in clean_scope if e.criterion == "quality").measured
    blank = envelope(rows=changed[:2])
    writes = []

    def capture(conn, cursor, sql, params, context, many):
        if ("index_daily_price" in sql or "index_price_year" in sql) and sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)

    event.listen(q.mysql.engine, "before_cursor_execute", capture)
    try:
        await manager.registry.get("archive.worker").fingerprints.invalidate(FINGERPRINT_NAMESPACE, "ths")
        await publish(blank)
        await publish(blank.model_copy(update={"observed_at": blank.observed_at + timedelta(microseconds=1)}))
        assert not writes
    finally:
        event.remove(q.mysql.engine, "before_cursor_execute", capture)
    await publish(envelope().model_copy(update={"observed_at": blank.observed_at + timedelta(seconds=1)}))
    await publish(blank)
    assert (await q.browse(CODE))["rows"][0]["amount"] == 1000
    assert await store.client.xlen(store.stream) == 0


async def test_explicit_amount_migration_preserves_content(prices, monkeypatch):
    import importlib

    from empire.core.config import project_root
    monkeypatch.syspath_prepend(str(project_root() / "scripts"))
    maintenance = importlib.import_module("migrate_index_price_amount")
    contents = importlib.import_module("migrate_index_price_nulls").contents
    _, c, q, _, _ = prices
    await c.execute()

    def check():
        with q.mysql.engine.connect() as conn:
            conn.exec_driver_sql("ALTER TABLE index_daily_price "
                                 "MODIFY amount DECIMAL(24,4) NOT NULL, "
                                 "ADD CONSTRAINT ck_index_price_volume CHECK (volume>=0 AND amount>=0)")
            conn.commit()
            before = contents(conn)
            assert maintenance.migrate(conn)
            assert contents(conn) == before
            assert not maintenance.migrate(conn)
    await q.mysql.control(check)


async def test_same_count_sql_set_corruption_fails_preparation(prices):
    _, c, q, _, _ = prices
    await c.execute()

    def corrupt():
        with q.mysql.engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE index_daily_price SET trade_date='2025-12-29' WHERE index_code=:code AND trade_date='2025-12-30'"
                ),
                dict(code=CODE),
            )

    await q.mysql.control(corrupt)
    checks = await q.preparation_check(dict(index_codes=[CODE]))
    assert next(e for e in checks if e.criterion == "coverage").status == "fail"


async def test_nullable_source_archive_query_and_later_fill(prices):
    from empire.features.index_prices.source import annual, recent
    from tests.test_ths_index_prices import source
    manager, c, q, store, publish = prices
    await c.execute()
    rows = copy.deepcopy(ROWS[:2])
    for row in rows:
        row[1:4] = [None, None, None]
    snapshot = recent(source(rows=rows + ROWS[2:]), CODE)
    parsed = annual(source(2025, rows), CODE, 2025, snapshot)
    now = datetime.now(UTC)
    missing = envelope(parsed).model_copy(update={"observed_at": now})
    await publish(missing)
    actual = (await q.browse(CODE, "2025-01-01", "2025-12-31"))["rows"]
    assert len(actual) == 2 and all(r["open"] is None and r["high"] is None and r["low"] is None for r in actual)
    assert actual[0]["close"] == 11 and actual[0]["amount"] == 1000
    checks = await q.preparation_check(dict(index_codes=[CODE], start="2025-01-01", end="2025-12-31"))
    quality = next(e for e in checks if e.criterion == "quality")
    assert quality.status == "pass" and "2条" in quality.measured and "NULL" in quality.measured
    writes = []

    def capture(conn, cursor, sql, params, context, many):
        if ("index_daily_price" in sql or "index_price_year" in sql) and sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)

    event.listen(q.mysql.engine, "before_cursor_execute", capture)
    try:
        await publish(missing)
        await manager.registry.get("archive.worker").fingerprints.invalidate(FINGERPRINT_NAMESPACE, "ths")
        await publish(missing)
        assert writes == []
    finally:
        event.remove(q.mysql.engine, "before_cursor_execute", capture)
    await publish(envelope().model_copy(update={"observed_at": now + timedelta(seconds=2)}))
    await publish(missing)
    actual = (await q.browse(CODE, "2025-01-01", "2025-12-31"))["rows"]
    assert actual[0]["open"] == 10
    assert (await q.year_heads(CODE))["2025"]["complete"]
    assert await store.client.xlen(store.stream) == 0


async def test_explicit_nullable_migration_preserves_business_and_is_idempotent(prices, monkeypatch):
    import importlib

    from empire.core.config import project_root

    monkeypatch.syspath_prepend(str(project_root() / "scripts"))
    maintenance = importlib.import_module("migrate_index_price_nulls")
    _, c, q, _, _ = prices
    await c.execute()

    def check():
        with q.mysql.engine.connect() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE index_daily_price DROP CHECK ck_index_price_ohlc, "
                "MODIFY open DECIMAL(18,6) NOT NULL, MODIFY high DECIMAL(18,6) NOT NULL, "
                "MODIFY low DECIMAL(18,6) NOT NULL, "
                "ADD CONSTRAINT ck_index_price_ohlc CHECK "
                "(low > 0 AND low <= open AND open <= high AND low <= close AND close <= high)"
            )
            conn.commit()
            before = maintenance.contents(conn)
            assert maintenance.migrate(conn)
            assert maintenance.contents(conn) == before
            assert not maintenance.migrate(conn)

    await q.mysql.control(check)


async def test_source_price_anomaly_archive_quality_replay_and_revision(prices):
    from tests.test_ths_index_prices import source
    manager, c, q, store, publish = prices
    original = c.http.request.side_effect
    changed = copy.deepcopy(ROWS)
    changed[0][1] = "8"  # Source open below low; preserve instead of guessing a correction.

    def response(method, address, **kw):
        unit = address.rsplit("/", 1)[1].split(".")[0]
        if unit == "last":
            body = source(rows=changed)
        else:
            body = source(unit, [r for r in changed if r[0][:4] == unit])
        return httpx.Response(200, content=body.encode())

    c.http.request.side_effect = response
    await c.execute()
    values = (await q.browse(CODE))["rows"]
    assert values[0]["open"] == 8 and values[0]["low"] == 9
    assert values[0]["price_relation_valid"] is False
    assert all(v["complete"] for v in (await q.year_heads(CODE)).values())
    checks = await q.preparation_check(dict(index_codes=[CODE]))
    assert next(e for e in checks if e.criterion == "coverage").status == "pass"
    quality = next(e for e in checks if e.criterion == "quality")
    assert quality.status == "fail" and "1条价格关系异常" in quality.measured
    clean_scope = await q.preparation_check(dict(index_codes=[CODE], start="2025-12-31", end="2025-12-31"))
    assert next(e for e in clean_scope if e.criterion == "quality").status == "pass"
    replay = envelope(rows=changed[:2])
    writes = []

    def capture(conn, cursor, sql, params, context, many):
        if ("index_daily_price" in sql or "index_price_year" in sql) and sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)

    event.listen(q.mysql.engine, "before_cursor_execute", capture)
    try:
        await manager.registry.get("archive.worker").fingerprints.invalidate(FINGERPRINT_NAMESPACE, "ths")
        await publish(replay)  # Cold SQL comparison of unchanged anomalous content.
        await publish(replay.model_copy(update={"observed_at": replay.observed_at + timedelta(microseconds=1)}))
        assert not writes  # Hot fingerprint confirmation also has no business DML.
    finally:
        event.remove(q.mysql.engine, "before_cursor_execute", capture)
    assert await store.client.xlen(store.stream) == 0
    corrected = envelope().model_copy(update={"observed_at": replay.observed_at + timedelta(seconds=1)})
    await publish(corrected)
    await publish(replay)  # Late anomalous content must not overwrite correction.
    assert (await q.browse(CODE))["rows"][0]["price_relation_valid"] is True
    assert await store.client.xlen(store.stream) == 0
    c.http.request.side_effect = original


async def test_explicit_price_quality_migration_keeps_content(prices, monkeypatch):
    import importlib

    from empire.core.config import project_root
    monkeypatch.syspath_prepend(str(project_root() / "scripts"))
    maintenance = importlib.import_module("migrate_index_price_quality")
    contents = importlib.import_module("migrate_index_price_nulls").contents
    _, c, q, _, _ = prices
    await c.execute()

    def check():
        with q.mysql.engine.connect() as conn:
            conn.exec_driver_sql(
                "ALTER TABLE index_daily_price DROP CHECK ck_index_price_ohlc, "
                "ADD CONSTRAINT ck_index_price_ohlc CHECK (close > 0 AND (open IS NULL OR open > 0) "
                "AND (high IS NULL OR high > 0) AND (low IS NULL OR low > 0) "
                "AND (low IS NULL OR high IS NULL OR low <= high) "
                "AND (low IS NULL OR open IS NULL OR low <= open) "
                "AND (high IS NULL OR open IS NULL OR open <= high) "
                "AND (low IS NULL OR low <= close) AND (high IS NULL OR close <= high))"
            )
            conn.commit()
            before = contents(conn)
            assert maintenance.migrate(conn)
            assert contents(conn) == before
            assert not maintenance.migrate(conn)
    await q.mysql.control(check)


@pytest.mark.parametrize("recovers", [True, False])
async def test_annual_404_shared_retry_to_archive_and_failed_checkpoint(prices, recovers):
    from empire.plugins.infra.http import HttpService
    from empire.plugins.infra.routing import USE_PROXY
    from tests.test_ths_index_prices import source

    manager, c, q, store, _ = prices
    attempts, first_checkpoint = [], []

    async def handle(request):
        unit = request.url.path.rsplit("/", 1)[1].split(".")[0]
        attempts.append(unit)
        if unit == "2025" and (not recovers or attempts.count(unit) == 1):
            first_checkpoint.append(await c.ingest.checkpoint(JOB))
            return httpx.Response(404)
        values = ROWS if unit == "last" else [r for r in ROWS if r[0][:4] == unit]
        return httpx.Response(200, content=source(unit, values).encode())

    service = HttpService(store.client, store.prefix,
                          {"ths": {"domains": ["10jqka.com.cn"], "min_interval_ms": 1, "max_concurrency": 1}},
                          records=c.records, transport=httpx.MockTransport(handle))
    c.http, c.request_retries = service, 1
    token = USE_PROXY.set(False)  # Isolated MockTransport; no source or proxy traffic.
    try:
        if recovers:
            await c.execute()
            assert len((await q.browse(CODE))["rows"]) == 3
            assert all(v["complete"] for v in (await q.year_heads(CODE)).values())
            checks = await q.preparation_check(dict(index_codes=[CODE]))
            assert next(e for e in checks if e.criterion == "coverage").status == "pass"
        else:
            with pytest.raises(httpx.HTTPStatusError):
                await c.execute()
            state = await c.ingest.checkpoint(JOB)
            assert state["cursor"]["next_year"] == 1990
            assert state["cursor"]["next_index"] == 0
            assert not (await q.browse(CODE))["rows"]
        assert attempts.count("2025") == 2
        assert all(s["cursor"]["next_year"] == 1990 for s in first_checkpoint)
        await manager.registry.get("archive.worker").flush()
        assert await store.client.xlen(store.stream) == 0 and service.buffer_budget.used == 0
    finally:
        USE_PROXY.reset(token)
        await service.close()


async def test_source_negative_quantity_archive_scope_replay_and_correction(prices):
    from tests.test_ths_index_prices import source
    manager, c, q, store, publish = prices
    changed = copy.deepcopy(ROWS)
    changed[0][5:7] = ["-100", "-798120910000"]

    def response(method, address, **kw):
        unit = address.rsplit("/", 1)[1].split(".")[0]
        body = source(rows=changed) if unit == "last" else source(unit, [r for r in changed if r[0][:4] == unit])
        return httpx.Response(200, content=body.encode())

    c.http.request.side_effect = response
    await c.execute()
    assert (await q.browse(CODE))["rows"][0]["amount"] == -798120910000
    assert (await q.browse(CODE))["rows"][0]["volume_amount_valid"] is False
    assert (await q.year_heads(CODE))["2025"]["complete"]
    checks = await q.preparation_check(dict(index_codes=[CODE]))
    quality = next(e for e in checks if e.criterion == "quality")
    assert quality.status == "pass" and "1条量额异常" in quality.measured
    clean_scope = await q.preparation_check(dict(index_codes=[CODE], start="2025-12-31", end="2025-12-31"))
    assert "0条量额异常" in next(e for e in clean_scope if e.criterion == "quality").measured
    blank = envelope(rows=changed[:2])
    writes = []

    def capture(conn, cursor, sql, params, context, many):
        if ("index_daily_price" in sql or "index_price_year" in sql) and sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(sql)

    event.listen(q.mysql.engine, "before_cursor_execute", capture)
    try:
        await manager.registry.get("archive.worker").fingerprints.invalidate(FINGERPRINT_NAMESPACE, "ths")
        await publish(blank)
        await publish(blank.model_copy(update={"observed_at": blank.observed_at + timedelta(microseconds=1)}))
        assert not writes
    finally:
        event.remove(q.mysql.engine, "before_cursor_execute", capture)
    await publish(envelope().model_copy(update={"observed_at": blank.observed_at + timedelta(seconds=1)}))
    await publish(blank)
    assert (await q.browse(CODE))["rows"][0]["amount"] == 1000
    assert await store.client.xlen(store.stream) == 0


async def test_explicit_numeric_quality_migration_preserves_content(prices, monkeypatch):
    import importlib

    from empire.core.config import project_root
    monkeypatch.syspath_prepend(str(project_root() / "scripts"))
    maintenance = importlib.import_module("migrate_index_price_numeric_quality")
    contents = importlib.import_module("migrate_index_price_nulls").contents
    _, c, q, _, _ = prices
    await c.execute()
    def check():
        with q.mysql.engine.connect() as conn:
            conn.exec_driver_sql("ALTER TABLE index_daily_price ADD CONSTRAINT ck_index_price_volume "
                                 "CHECK (volume>=0 AND (amount IS NULL OR amount>=0))")
            conn.commit()
            before = contents(conn)
            assert maintenance.migrate(conn)
            assert contents(conn) == before
            assert not maintenance.migrate(conn)
    await q.mysql.control(check)
