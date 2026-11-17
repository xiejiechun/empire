import asyncio
from types import SimpleNamespace

import httpx
import pytest

from empire.contracts.download import ResponsePolicy
from empire.contracts.request_cost import add_cost, measured_run, request_kind
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.stream_exchange import BoundedChannel
from tests.test_http import MemoryPermits, groups


def test_operational_snapshot_retains_only_bounded_numeric_costs():
    from empire.plugins.collection.progress import display_snapshot
    assert display_snapshot(dict(network_costs=dict(http_attempts=2, retries=-1,
        native_queries=True, secret='not retained'))) == {'network_costs': {'http_attempts': 2}}


async def test_real_http_attempts_include_failure_body_retry_and_auth(monkeypatch):
    monkeypatch.setattr('empire.plugins.infra.http.retry_delay', lambda _: 0)
    replies = [httpx.Response(503, content=b'fail'), httpx.Response(200, content=b'ok')]
    http = HttpService(MemoryPermits(), 'test', groups(1), transport=httpx.MockTransport(lambda _: replies.pop(0)))
    c = SimpleNamespace(stats={})
    @measured_run
    async def run(self):
        with request_kind('authentication'):
            response = await http.request('GET', 'https://finance.sina.com.cn/', allowed_domains=('sina.com.cn',), max_retries=1)
            response.close()
        return {}
    try:
        result = await run(c)
        costs = result['network_costs']
        assert costs['http_attempts'] == costs['authentication_http_attempts'] == 2
        assert costs['retries'] == 1
        assert costs['observed_wire_bytes'] == costs['observed_body_bytes'] == 6
    finally:
        await http.close()


async def test_concurrent_runs_are_isolated_and_children_accumulate():
    @measured_run
    async def run(self, n):
        async def child():
            await asyncio.sleep(0)
            add_cost('native_queries')
        await asyncio.gather(*(child() for _ in range(n)))
        return {}
    a, b = SimpleNamespace(stats={}), SimpleNamespace(stats={})
    results = await asyncio.gather(run(a, 3), run(b, 7))
    assert [r['network_costs']['native_queries'] for r in results] == [3, 7]
    add_cost('native_queries', 100)
    assert a.stats['network_costs']['native_queries'] == 3


@pytest.mark.parametrize('cancel', [False, True])
async def test_failed_or_cancelled_run_keeps_observed_partial_bytes(cancel):
    reader = asyncio.StreamReader()
    reader.feed_data(b'abc')
    reader.feed_eof()
    channel = BoundedChannel(reader, None, ResponsePolicy(100, 100))
    c = SimpleNamespace(stats={})
    @measured_run
    async def run(self):
        if cancel:
            add_cost('observed_wire_bytes', 3)
            raise asyncio.CancelledError
        await channel.readexactly(8)
    with pytest.raises(asyncio.CancelledError if cancel else asyncio.IncompleteReadError):
        await run(c)
    assert c.stats['network_costs']['observed_wire_bytes'] == 3
