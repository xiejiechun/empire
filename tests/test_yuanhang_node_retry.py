"""Node rotation and unavailable-directory windows share the saved retry budget."""
import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.yuanhang import node_selection
from tests.test_yuanhang_collector import collector


@pytest.fixture
def clock(monkeypatch):
    timer = [0.0]
    monkeypatch.setattr(node_selection, 'monotonic', lambda: timer[0])
    async def tick(seconds):
        timer[0] += seconds
        await asyncio.sleep(0)
    monkeypatch.setattr(node_selection, 'sleep', tick)
    return timer


@pytest.mark.parametrize('financial', [False, True])
async def test_directory_outage_over_125_seconds_recovers_on_next_budgeted_attempt(monkeypatch, clock, financial):
    c = collector(monkeypatch)
    c.financial, c.request_retries = financial, 3
    def online():
        return {'node001'} if clock[0] == 0 else {'node002'} if clock[0] >= 150 else set()
    c.identity.online_codes = online
    async def request(node, *args, fresh_connection=False):
        assert fresh_connection is False
        if node == 'node001':
            clock[0] = 1
            raise httpx.ProxyError('secret')
        return 'snapshot'
    c.fetch_authenticated = AsyncMock(side_effect=request)
    assert await c.fetch(('000902.SZ', 'node001', '2026-11-09')) == 'snapshot'
    assert [call.args[0] for call in c.fetch_authenticated.await_args_list] == ['node001', 'node002']
    assert c.stats['node_unavailable_retries'] == 1


@pytest.mark.parametrize('budget', [0, 1, 30])
async def test_unavailable_windows_exhaust_budget_without_inventing_network_requests(monkeypatch, clock, budget):
    c = collector(monkeypatch)
    c.request_retries = budget
    c.identity.online_codes = lambda: set()
    c.fetch_authenticated = AsyncMock()
    with pytest.raises(ValueError) as caught:
        await c.fetch(('000917.SZ', 'node001', '2026-11-09'))
    assert clock[0] == 125 * (budget + 1)
    assert c.stats.get('node_unavailable_retries', 0) == budget
    assert not c.fetch_authenticated.await_count
    detail = caught.value.yuanhang_diagnostics
    assert detail['attempt'] == detail['attempt_limit'] == budget + 1
    assert detail['remaining_retries'] == 0


async def test_another_healthy_node_precedes_reusing_last_failure(monkeypatch, clock):
    c = collector(monkeypatch)
    node = await node_selection.select_node(c.identity, 'node001', {'node001': 1, 'node002': 5},
        diagnostics={'failures': [{'node': 'node001'}]})
    assert node == 'node002' and clock[0] == 0


async def test_cancel_during_later_selection_window_stops_retry(monkeypatch, clock):
    c = collector(monkeypatch)
    c.request_retries = 30
    c.identity.online_codes = lambda: set()
    async def cancel(seconds):
        raise asyncio.CancelledError()
    monkeypatch.setattr(node_selection, 'sleep', cancel)
    with pytest.raises(asyncio.CancelledError):
        await c.fetch(('000001.SZ', None, '2026-11-09'))
    assert not c.stats.get('node_unavailable_retries')
