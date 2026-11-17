"""Conflicting source symbols preserve SQL while valid siblings archive and recover."""
import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine

from empire.contracts.collector import CollectionSourceGap
from empire.features.fx.contract import DAILY_JOB
from tests.integration.test_fx_archive import fx, pytestmark  # noqa: F401
from tests.test_fx_source_gaps import CODES, gap_collector
from tests.test_fx_verification import CLOSED, OLD


async def test_source_conflict_archives_siblings_preserves_resume_and_recovers(fx, monkeypatch):  # noqa: F811
    _, c, query, redis, _ = fx
    sample, faults = gap_collector(monkeypatch, 'XAUUSD')
    c.http, c.selected_codes = sample.http, CODES
    with pytest.raises(CollectionSourceGap, match='XAUUSD'):
        await asyncio.wait_for(c.execute(), 20)
    before = await c.ingest.checkpoint(DAILY_JOB)
    assert before['cursor']['next_index'] == 1 and before['cursor']['phase'] == 'collecting'
    assert before['cursor']['pages'] == 2 and c.stats['completed_units'] == 2
    assert await query.history('XAUUSD', 2026) == []
    for code in ('USDIND', 'EURUSD'):
        assert await query.history(code, 2026) == [CLOSED]
    assert await redis.client.xlen(redis.stream) == 0
    errors = await c.records.list_error_summaries(c.project_id)
    error = await c.records.get_error(c.project_id, errors['rows'][0]['id'])
    assert error['metadata']['annuals']['2026']['tail'][0] == ' | '.join(OLD)
    writes = []
    def capture(conn, cursor, sql, *args):
        if 'fx_' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(Engine, 'before_cursor_execute', capture)
    try:
        with pytest.raises(CollectionSourceGap):
            await asyncio.wait_for(c.execute(baseline_revision=before['revision']), 20)
        assert writes == [] and await redis.client.xlen(redis.stream) == 0
    finally:
        event.remove(Engine, 'before_cursor_execute', capture)
    before = await c.ingest.checkpoint(DAILY_JOB)
    faults.clear()
    assert (await asyncio.wait_for(c.execute(baseline_revision=before['revision']), 20))['phase'] == 'complete'
    for code in CODES:
        assert await query.history(code, 2026) == [CLOSED]
    assert await redis.client.xlen(redis.stream) == 0
