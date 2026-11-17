"""Native empty-day gaps never replace stored candles or block valid siblings."""
import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.contracts.collector import CollectionSourceGap
from empire.features.fx.contract import DAILY_JOB
from tests.integration.test_fx_archive import fx, pytestmark  # noqa: F401
from tests.test_fx_daily_empty_prices import daily_empty_collector
from tests.test_fx_source_gaps import CODES
from tests.test_fx_verification import CLOSED


async def test_native_empty_day_preserves_sql_archives_others_and_recovers(fx, monkeypatch):  # noqa: F811
    _, c, query, redis, _ = fx
    failures = set()
    sample = daily_empty_collector(monkeypatch, failures)
    c.http, c.selected_codes = sample.http, CODES
    assert (await asyncio.wait_for(c.execute(), 20))['phase'] == 'complete'
    before = await c.ingest.checkpoint(DAILY_JOB)
    failures.add(CODES[1])
    writes = []
    def capture(conn, cursor, sql, *args):
        if 'fx_' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(Engine, 'before_cursor_execute', capture)
    try:
        for _ in range(2):
            with pytest.raises(CollectionSourceGap, match='当日日线暂无报价'):
                await asyncio.wait_for(c.execute(baseline_revision=before['revision']), 20)
            before = await c.ingest.checkpoint(DAILY_JOB)
            assert before['cursor']['next_index'] == 1 and before['cursor']['phase'] == 'collecting'
            assert writes == [] and await redis.client.xlen(redis.stream) == 0
            for code in CODES:
                assert await query.history(code, 2026) == [CLOSED]
        assert (await c.records.list_error_summaries(c.project_id))['rows'] == []
        failures.clear()
        assert (await asyncio.wait_for(c.execute(baseline_revision=before['revision']), 20))['phase'] == 'complete'
        assert writes == [] and await redis.client.xlen(redis.stream) == 0
        assert c.stats['unavailable_codes'] == [] and c.stats['notice'] == ''
    finally:
        event.remove(Engine, 'before_cursor_execute', capture)


async def test_all_empty_daily_does_not_publish_or_advance_checkpoint(fx, monkeypatch):  # noqa: F811
    _, c, query, redis, _ = fx
    sample = daily_empty_collector(monkeypatch, set(CODES))
    c.http, c.selected_codes = sample.http, CODES
    before = await c.ingest.checkpoint(DAILY_JOB)
    with pytest.raises(CollectionSourceGap, match='0/3'):
        await asyncio.wait_for(c.execute(), 20)
    assert await c.ingest.checkpoint(DAILY_JOB) == before
    assert await redis.client.xlen(redis.stream) == 0
    assert (await c.records.list_error_summaries(c.project_id))['rows'] == []
    for code in CODES:
        assert await query.history(code, 2026) == []
