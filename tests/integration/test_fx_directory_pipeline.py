"""Directory lag flows through the formal archive; invalid counts preserve state."""
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


async def test_directory_lag_archive_query_repeat_and_failed_count_preserve_state(fx, monkeypatch):  # noqa: F811
    _, c, q, redis, publish = fx
    monkeypatch.setattr('empire.features.fx.transport.datetime', SimpleNamespace(now=lambda _: NOW + timedelta(seconds=1)))
    await publish(envelope([OLD], year=2026, source_count=1, start=OLD[0], end=OLD[0])
                  .model_copy(update={'observed_at': NOW}))
    bad = False
    def request(method, url, **kwargs):
        if '/today.js' in url:
            body = today_source(CURRENT)
        elif '/last.js' in url:
            body = source(rows=[CLOSED], start='20261109', year={'2026': 1}, total='1')
        else:
            rows = [CLOSED, CURRENT]
            if bad:
                rows.insert(0, ['2026-11-06', *CLOSED[1:]])
            body = source(2026, rows)
        return httpx.Response(200, content=body.encode())
    c.http.request.side_effect = request
    assert (await asyncio.wait_for(c.execute(), 20))['phase'] == 'complete'
    assert c.http.request.await_count == 3
    rows = (await q.browse(CODE))['rows']
    assert len(rows) == 1 and str(rows[0]['close']) == CLOSED[4] + '00000'
    assert await redis.client.xlen(redis.stream) == 0
    writes = []
    def capture(conn, cursor, sql, *args):
        if 'fx_' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(Engine, 'before_cursor_execute', capture)
    try:
        before = await c.ingest.checkpoint(DAILY_JOB)
        assert (await asyncio.wait_for(c.execute(baseline_revision=before['revision']), 20))['phase'] == 'complete'
        assert writes == [] and await redis.client.xlen(redis.stream) == 0
        before = await c.ingest.checkpoint(DAILY_JOB)
        bad = True
        with pytest.raises(CollectionSourceGap, match='USDCNH'):
            await c.execute(baseline_revision=before['revision'])
        assert await c.ingest.checkpoint(DAILY_JOB) == before
        assert (await q.browse(CODE))['rows'] == rows
        assert writes == [] and await redis.client.xlen(redis.stream) == 0
        errors = await c.records.list_error_summaries(c.project_id)
        assert errors['total'] == 1
        error = await c.records.get_error(c.project_id, errors['rows'][0]['id'])
        assert error['metadata']['kind'] == 'cross_response_validation'
        assert error['metadata']['annuals']['2026']['count'] == 3
        assert error['metadata']['annuals']['2026']['directory'] == 1
        assert error['metadata']['annuals']['2026']['tail'][-1] == ' | '.join(CURRENT)
    finally:
        event.remove(Engine, 'before_cursor_execute', capture)
