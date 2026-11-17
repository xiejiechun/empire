"""A separately counted active day must never enter durable daily history."""
import asyncio
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.contracts.collector import CollectionSourceGap
from empire.features.fx.contract import DAILY_JOB
from tests.integration.test_fx_archive import fx, pytestmark  # noqa: F401
from tests.test_fx import CODE, envelope, source, today_source
from tests.test_fx_verification import CLOSED, CURRENT, NOW, OLD


async def test_reserved_day_source_to_archive_query_replay_and_conflict(fx, monkeypatch):  # noqa: F811
    _, c, query, redis, publish = fx
    monkeypatch.setattr('empire.features.fx.transport.datetime', SimpleNamespace(now=lambda _: NOW + timedelta(seconds=1)))
    await publish(envelope([OLD], year=2026, source_count=1, start=OLD[0], end=OLD[0])
        .model_copy(update={'observed_at': NOW}))
    conflict = False
    def request(method, target, **kwargs):
        assert '/realhead/' not in target
        if target.endswith('today.js'):
            body = today_source(CURRENT)
        elif target.endswith('last.js'):
            body = source(rows=[CLOSED], start='20261109', year={'2026': 2}, total='2')
        else:
            body = source(2026, [OLD if conflict else CLOSED])
        return httpx.Response(200, content=body.encode())
    c.http.request.side_effect = request
    assert (await asyncio.wait_for(c.execute(), 20))['phase'] == 'complete'
    assert await query.history(CODE, 2026) == [CLOSED]
    inventory = await query.inventory(CLOSED[0])
    assert inventory[CODE]['2026']['source_count'] == inventory[CODE]['2026']['row_count'] == 1
    assert await redis.client.xlen(redis.stream) == 0
    writes = []
    def capture(conn, cursor, sql, *args):
        if 'fx_' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(Engine, 'before_cursor_execute', capture)
    try:
        before = await c.ingest.checkpoint(DAILY_JOB)
        assert (await c.execute(baseline_revision=before['revision']))['phase'] == 'complete'
        assert writes == [] and await redis.client.xlen(redis.stream) == 0
        before = await c.ingest.checkpoint(DAILY_JOB)
        conflict = True
        with pytest.raises(CollectionSourceGap, match='内容不一致|来源日线核验缺口'):
            await c.execute(baseline_revision=before['revision'])
        assert await c.ingest.checkpoint(DAILY_JOB) == before
        assert await query.history(CODE, 2026) == [CLOSED]
        assert writes == [] and await redis.client.xlen(redis.stream) == 0
    finally:
        event.remove(Engine, 'before_cursor_execute', capture)
