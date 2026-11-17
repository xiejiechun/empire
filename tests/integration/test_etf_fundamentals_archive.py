import asyncio
import json
import os
from datetime import UTC, date, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.etf_fundamentals import nav_dataset, share_dataset
from empire.features.etf_fundamentals.collector import unpack_cursor
from empire.features.etf_fundamentals.contract import NAV_FIELDS, NUMERIC, START, number
from tests.prefetch_source import prefetch_http
from tests.test_etf_fundamentals import nav_response, sse_response, workbook

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
    redis = None
    try:
        await manager.start("collector.sse_etf_shares")
        await manager.start("collector.szse_etf_shares")
        await manager.start("collector.ttjj_etf_nav")
        q = manager.registry.get("etf.fundamentals.query")
        redis = manager.registry.get("redis.store")
        first, last = date.fromisoformat(START), date.today()
        with q.mysql.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO trade_calendar(trade_date,is_trade,updated_at) VALUES(:d,:t,NOW())"
                ),
                [
                    dict(
                        d=first + timedelta(days=i),
                        t=int((first + timedelta(days=i)).weekday() < 5),
                    )
                    for i in range((last - first).days + 1)
                ],
            )
        q.directory.catalog = AsyncMock(
            return_value=[dict(code="510300.SH", name="ETF", native_market="USHJ")]
        )
        yield manager, q, redis
    finally:
        await manager.shutdown()
        if redis:
            from empire.plugins.infra.redis_store import create_client

            client = create_client(cfg["redis"])
            keys = [k async for k in client.scan_iter(match=cfg["redis"]["namespace"] + ":*")]
            if keys:
                await client.delete(*keys)
            await client.aclose()


def install_source(c):
    def fetch(method, url, **kw):
        p = kw["params"]
        if c.source == "sse":
            d = sse_response([] if "JYXJJ" in p["sqlId"] else None)
            d["sqlId"] = p["sqlId"]
            for row in d["result"]:
                row["STAT_DATE"] = p["STAT_DATE"]
            raw = json.dumps(d).encode()
        elif c.source == "szse":
            stamp = p["txtStart"]
            if p["SHOWTYPE"] == "xlsx":
                raw = workbook([[stamp, "159001", "货币ETF", "4855333.00"]])
            else:
                raw = json.dumps(
                    [
                        dict(
                            metadata=dict(
                                catalogid="scsj_fund_jjgm",
                                recordcount=1,
                                pagecount=1,
                                pageno=1,
                                pagesize=20,
                            ),
                            data=[
                                dict(
                                    size_date=stamp,
                                    fund_code="159001",
                                    security_short_name="货币ETF",
                                    current_size="485.53",
                                )
                            ],
                            error=None,
                        )
                    ]
                ).encode()
        else:
            d = nav_response()
            raw = json.dumps(d).encode()
        return httpx.Response(200, content=raw)

    c.http = prefetch_http(request=AsyncMock(side_effect=fetch))


@pytest.mark.parametrize("end", ["2004-12-30", "2004-12-31"])
async def test_first_etf_dates_have_short_default_windows(pipeline, end):
    _, q, _ = pipeline
    plan = await q.plan("ttjj", end=end)
    assert plan["units"] == [dict(code="510300.SH", start=START, through=end)]
    for source in ("ttjj", "sse", "szse"):
        checks = await getattr(q, "check_" + source)(dict(end=end))
        assert next(c for c in checks if c.criterion == "coverage").status == "fail"


async def collect(c):
    install_source(c)
    kw = (
        dict(codes=["510300.SH"], start="2026-11-13", end="2026-11-13")
        if c.source == "ttjj"
        else dict(sample_dates=["2026-11-13"])
    )
    return await asyncio.wait_for(
        c.execute(baseline_revision=await c.checkpoint_revision(), **kw), 20
    )


@pytest.mark.parametrize("source", ["sse", "szse", "ttjj"])
async def test_formal_pipeline_repeat_cold_cache_stale_revision_and_clean_queue(pipeline, source):
    manager, q, redis = pipeline
    project = "ttjj-etf-nav" if source == "ttjj" else source + "-etf-shares"
    c = manager.registry.get("collector." + project.replace("-", "_"))
    await collect(c)
    first = await q.browse(source=source)
    assert len(first["rows"]) == 1 and await redis.client.xlen(redis.stream) == 0
    mapping = nav_dataset if source == "ttjj" else share_dataset
    dml = []

    def track(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and any(
            t in sql for t in mapping.TABLES
        ):
            dml.append(sql)

    for engine in (q.mysql.engine, q.mysql.archive_engine):
        event.listen(engine, "before_cursor_execute", track)
    try:
        await collect(c)
        assert not dml
        archive = manager.registry.get("archive.worker")
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, source)
        await collect(c)
        assert not dml
        cursor = unpack_cursor((await c.ingest.checkpoint(c.job_key))["cursor"])
        unit = cursor["units"][0]
        rows, observed = await c.fetch_unit(unit, reservation=None)
        if source == "ttjj":
            rows[0][2] = "1.3"
            payload = dict(
                page=1, code=unit["code"], start=unit["start"], through=unit["through"], rows=rows
            )
            key = "510300.SH:2026"
        else:
            rows[0][2] = "1000001"
            payload = dict(page=1, date=unit["date"], rows=rows)
            key = unit["date"]
        e = make_envelope(
            source=source,
            dataset=c.dataset,
            business_key=key,
            job_key=c.job_key,
            batch_id="revision",
            run_id="revision",
            payload=payload,
        )
        await archive._archive_data(e, mapping.normalize(e))
        revised = await q.browse(source=source)
        assert revised != first and dml
        dml.clear()
        stale = e.model_copy(update=dict(observed_at=datetime.now(UTC) - timedelta(days=1)))
        await archive.fingerprints.invalidate(mapping.FINGERPRINT_NAMESPACE, source)
        await archive._archive_data(stale, mapping.normalize(stale))
        assert not dml and await q.browse(source=source) == revised
    finally:
        for engine in (q.mysql.engine, q.mysql.archive_engine):
            event.remove(engine, "before_cursor_execute", track)


async def test_sql_failure_and_post_commit_replay_retain_exact_message(pipeline, monkeypatch):
    manager, q, redis = pipeline
    c = manager.registry.get("collector.sse_etf_shares")
    archive = manager.registry.get("archive.worker")
    await archive.stop()
    archive.stop_event.clear()
    task = asyncio.create_task(collect(c))
    async with asyncio.timeout(5):
        while await redis.client.xlen(redis.stream) != 1:
            await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    original = share_dataset.write

    def fail(*a):
        original(*a)
        raise RuntimeError("transaction failure")

    monkeypatch.setattr(share_dataset, "write", fail)
    with pytest.raises(RuntimeError, match="transaction failure"):
        await archive.flush()
    assert (await q.browse(source="sse"))["rows"] == [] and await redis.client.xlen(
        redis.stream
    ) == 1
    monkeypatch.setattr(share_dataset, "write", original)
    put = archive.fingerprints.put
    monkeypatch.setattr(
        archive.fingerprints, "put", AsyncMock(side_effect=RuntimeError("post commit"))
    )
    with pytest.raises(RuntimeError, match="post commit"):
        await archive.flush()
    assert (
        len((await q.browse(source="sse"))["rows"]) == 1
        and await redis.client.xlen(redis.stream) == 1
    )
    monkeypatch.setattr(archive.fingerprints, "put", put)
    await archive.flush()
    assert await redis.client.xlen(redis.stream) == 0


async def test_same_count_replacement_and_content_bound_preparation(pipeline):
    manager, q, redis = pipeline
    c = manager.registry.get("collector.sse_etf_shares")
    await collect(c)
    checks = await q.check_sse(dict(start="2026-11-13", end="2026-11-13"))
    assert next(x for x in checks if x.criterion == "coverage").status == "pass"
    rows = [["510050.SH", "替换ETF", "100", "etf", None]]
    e = make_envelope(
        source="sse",
        dataset=c.dataset,
        business_key="2026-11-13",
        job_key=c.job_key,
        batch_id="replacement",
        run_id="replacement",
        payload=dict(page=1, date="2026-11-13", rows=rows),
    )
    archive = manager.registry.get("archive.worker")
    await archive._archive_data(e, share_dataset.normalize(e))
    result = await q.browse(source="sse")
    assert [r["unified_code"] for r in result["rows"]] == ["510050.SH"]
    assert await redis.client.xlen(redis.stream) == 0
    # Same row count with changed content cannot reuse the former proof.
    with q.mysql.engine.begin() as conn:
        conn.execute(
            text("UPDATE etf_daily_share SET total_shares=101 WHERE unified_code='510050.SH'")
        )
    checks = await q.check_sse(dict(start="2026-11-13", end="2026-11-13"))
    assert next(x for x in checks if x.criterion == "keys").status == "fail"


async def test_nav_withdrawal_empty_authority_and_old_overlap(pipeline):
    manager, q, redis = pipeline
    c = manager.registry.get("collector.ttjj_etf_nav")
    await collect(c)
    archive = manager.registry.get("archive.worker")
    first = (await q.browse())["rows"][0]
    observed = datetime.now(UTC) + timedelta(seconds=1)
    empty = make_envelope(
        source="ttjj",
        dataset=c.dataset,
        business_key="510300.SH:2026",
        job_key=c.job_key,
        batch_id="withdrawal",
        run_id="withdrawal",
        payload=dict(page=1, code="510300.SH", start="2026-11-13", through="2026-11-13", rows=[]),
    ).model_copy(update={"observed_at": observed})
    await archive._archive_data(empty, nav_dataset.normalize(empty))
    assert not (await q.browse())["rows"]
    old = empty.model_copy(
        update={
            "observed_at": observed - timedelta(seconds=2),
            "raw_payload": dict(
                page=1,
                code="510300.SH",
                start="2026-11-12",
                through="2026-11-13",
                rows=[
                    [
                        "2026-11-13",
                        *[number(first[f]) if f in NUMERIC else first[f] for f in NAV_FIELDS],
                    ]
                ],
            ),
        }
    )
    await archive.fingerprints.invalidate(nav_dataset.FINGERPRINT_NAMESPACE, "ttjj")
    await archive._archive_data(old, nav_dataset.normalize(old))
    assert not (await q.browse())["rows"]
    assert await redis.client.xlen(redis.stream) == 0
