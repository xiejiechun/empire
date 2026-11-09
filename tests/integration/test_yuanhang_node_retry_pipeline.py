"""Temporary node absence must respect retries and ordered archive publication."""
import asyncio
import os
from unittest.mock import AsyncMock

import pytest

from empire.features.yuanhang import node_selection
from tests.integration.test_yuanhang_archive import native as native
from tests.test_yuanhang_payload import CODE, bar, snapshot

pytestmark = [pytest.mark.integration,
    pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit private database')]


@pytest.fixture
def clock(monkeypatch):
    timer = [0.0]
    monkeypatch.setattr(node_selection, 'monotonic', lambda: timer[0])
    async def tick(seconds):
        timer[0] += seconds
        await asyncio.sleep(0)
    monkeypatch.setattr(node_selection, 'sleep', tick)
    return timer


async def test_offline_at_plan_recovers_publishes_archives_and_queries(native, monkeypatch, clock):
    _, c, query, store, archive = native
    c.request_retries = 2
    c.fetch = type(c).fetch.__get__(c)
    c.identity.online_codes = lambda: {'node-test'} if clock[0] >= 150 else set()
    c.fetch_authenticated = AsyncMock(return_value=snapshot((bar('2020-10-19'),)))
    monkeypatch.setattr('empire.features.yuanhang.collector.retry_delay', lambda n: 0)
    result = await c.execute(fresh=True)
    assert result['phase'] == 'complete'
    assert c.stats['node_unavailable_retries'] == 1
    assert c.fetch_authenticated.await_count == 1
    rows = (await query.prices(CODE))['rows']
    assert [r['trade_date'].isoformat() for r in rows] == ['2020-10-19']
    assert await store.client.xlen(store.stream) == 0


async def test_exhausted_selection_does_not_publish_or_advance_security(native, monkeypatch, clock):
    _, c, query, store, archive = native
    c.request_retries = 1
    c.fetch = type(c).fetch.__get__(c)
    c.identity.online_codes = lambda: set()
    c.fetch_authenticated = AsyncMock()
    monkeypatch.setattr('empire.features.yuanhang.collector.retry_delay', lambda n: 0)
    with pytest.raises(node_selection.NodeUnavailableError):
        await c.execute(fresh=True)
    assert clock[0] == 250 and not c.fetch_authenticated.await_count
    cursor = (await c.ingest.checkpoint(c.job_key))['cursor']
    assert cursor == {}  # Initial plan stays in memory until a valid unit publishes.
    assert (await query.prices(CODE))['rows'] == []
    assert await store.client.xlen(store.stream) == 0
    errors = await c.records.list_error_summaries(c.project_id, limit=10)
    error = await c.records.get_error(c.project_id, errors['rows'][0]['id'])
    assert error['metadata']['attempt'] == 2
    assert error['metadata']['remaining_retries'] == 0
