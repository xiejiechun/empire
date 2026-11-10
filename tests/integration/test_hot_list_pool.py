"""Authoritative current/historical pool and planning disconnect recovery."""

import asyncio
import os

import pytest
from sqlalchemy import event, text

from tests.integration.test_hot_list_archive import collect, pipeline  # noqa: F401
from tests.test_hot_list_pool import failure
from tests.test_tdx_hot_list import CODE, DATE

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Private SQL/Redis opt-in")]


async def test_pool_preserves_old_security_and_uses_covering_index(pipeline):  # noqa: F811
    _, c, q, store = pipeline
    await collect(c, fresh=True)

    def seed():
        with q.mysql.engine.begin() as conn:
            conn.execute(text("INSERT INTO stock(unified_code,name) VALUES(:code,'test')"),
                         [{"code": "000001.SZ"}, {"code": "920117.BJ"}])

    await asyncio.to_thread(seed)
    assert await q.securities() == sorted([CODE, "000001.SZ", "920117.BJ"])
    # Existing history survives absence from the current stock list.
    assert (await q.detail(CODE, DATE))["seats"]
    sql = "SELECT unified_code FROM stock UNION SELECT DISTINCT unified_code FROM hot_list_day FORCE INDEX (ix_date) ORDER BY unified_code LIMIT 30001"

    def plan():
        with q.mysql.read_engine.connect() as conn:
            return list(conn.execute(text("EXPLAIN " + sql)).mappings())

    assert any(r["table"] == "hot_list_day" and r["key"] == "ix_date"
               and "Using index" in r["Extra"] for r in await q.mysql.read(plan))
    assert await store.client.xlen(store.stream) == 0


@pytest.mark.parametrize("exhaust", [False, True])
async def test_planning_disconnect_retains_checkpoint_and_recovers(pipeline, exhaust):  # noqa: F811
    _, c, q, store = pipeline
    await collect(c, fresh=True)

    def seed():
        with q.mysql.engine.begin() as conn:
            conn.execute(text("INSERT INTO stock(unified_code,name) VALUES(:code,'test')"), {"code": CODE})

    await asyncio.to_thread(seed)
    before = await c.ingest.checkpoint(c.job_key)
    attempts = []

    def disconnect(conn, cursor, sql, parameters, context, many):
        if "FROM stock UNION" in sql:
            attempts.append(sql)
            if exhaust or len(attempts) == 1:
                conn.invalidate()
                raise failure()

    event.listen(q.mysql.read_engine, "before_cursor_execute", disconnect)
    try:
        if exhaust:
            with pytest.raises(type(failure())):
                await c.execute(baseline_revision=before["revision"])
            assert len(attempts) == 2
            assert await c.ingest.checkpoint(c.job_key) == before
            assert await store.client.xlen(store.stream) == 0
        else:
            result = await c.execute(baseline_revision=before["revision"])
            assert result["phase"] == "complete" and len(attempts) == 2
    finally:
        event.remove(q.mysql.read_engine, "before_cursor_execute", disconnect)
    if exhaust:
        result = await c.execute(baseline_revision=before["revision"])
        assert result["phase"] == "complete"
    assert result["batch_id"] != before["cursor"]["batch_id"]
    assert (await q.detail(CODE, DATE))["seats"]
    assert await store.client.xlen(store.stream) == 0
