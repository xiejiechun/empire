"""The real downloader borrows one lease; response close never releases it early."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.resources import ByteBudget
from empire.plugins.infra.response_reader import ManagedResponse
from tests.test_cninfo_calendar import collector as calendar


def service():
    http = HttpService(None, 'test', {})
    http.parallelism = AsyncMock(return_value=10)
    size = http.response_policy().reservation_bytes
    http.buffer_budget = ByteBudget(2 * size)
    return http, size


async def test_managed_response_close_keeps_retained_unit_budget_until_ordered_consumption():
    http, size = service()
    c = SimpleNamespace(http=http, stats={})
    responses, used, seen = [], [], []
    async def transport(method, url, **kw):
        original = httpx.Response(200, request=httpx.Request(method, url), json={'url': url})
        response = ManagedResponse(original, original.content)
        responses.append(response)
        return response
    http._request = AsyncMock(side_effect=transport)
    async def fetch(unit, *, reservation):
        response = await http.request('GET', 'https://example.com/' + str(unit), reservation=reservation)
        async def consume():
            value = response.json()
            response.close()
            used.append(http.buffer_budget.used)
            return value
        return DeferredResponse(response, consume)
    try:
        async with prefetch_units(c, list(range(5)), fetch, url='https://example.com/',
                                  domains=('example.com',)) as reads:
            async for index, read in reads:
                seen.append((index, (await read.resolve())['url']))
                assert http.buffer_budget.used >= size
        assert [i for i, _ in seen] == list(range(5))
        assert used[0] == http.buffer_budget.peak == 2 * size
        assert http.buffer_budget.used == 0 and not http.responses
        assert all(r.content == b'' for r in responses)
    finally:
        await http.close()


async def test_error_diagnostics_capture_real_managed_body_before_drain():
    c = calendar()
    http, _ = service()
    original = httpx.Response(200, request=httpx.Request('GET', 'https://www.cninfo.com.cn/data/tradeday/getMonthTradeDay'),
                              content=b'{"monthTradeDate":[]}')
    response = ManagedResponse(original, original.content)
    http._request = AsyncMock(return_value=response)
    c.http = http
    try:
        with pytest.raises(ValueError):
            await c.execute()
        c.records.add_error.assert_awaited_once()
        assert c.records.add_error.call_args.kwargs['raw_body'] == original.content
        assert response.content == b'' and not http.responses
        assert http.buffer_budget.used == 0 and c.ingest.state['revision'] == 0
    finally:
        await http.close()


async def test_dependent_page_contract_never_asks_for_parallel_width():
    http, size = service()
    c = SimpleNamespace(http=http, stats={})
    starts = []
    async def fetch(unit, *, reservation):
        starts.append(unit)
        await asyncio.sleep(0)
        return unit
    try:
        async with prefetch_units(c, [0, 1, 2], fetch, url='https://example.com/',
                                  domains=('example.com',), independent=False) as reads:
            async for index, read in reads:
                assert starts == list(range(index + 1))
                assert await read.resolve() == index
                assert http.buffer_budget.used == size
        http.parallelism.assert_not_awaited()
        assert http.buffer_budget.used == 0
    finally:
        await http.close()


@pytest.mark.parametrize('cancel', [False, True])
async def test_retained_result_budget_is_owned_until_consumption_or_cancellation(cancel):
    http, size = service()
    retained = 1024
    total = size + 3 * retained
    http.buffer_budget = ByteBudget(2 * total)
    c = SimpleNamespace(http=http, stats={})
    started = asyncio.Event()
    reservations = []

    async def fetch(unit, *, reservation):
        reservations.append(reservation)
        assert reservation.size == size
        assert reservation.owner.size == total
        reservation.release()
        assert not reservation.released
        started.set()
        if cancel:
            await asyncio.Event().wait()
        return unit

    async def run():
        async with prefetch_units(c, [0, 1, 2], fetch, url='https://example.com/',
                                  domains=('example.com',), retained_bytes=retained) as reads:
            async for index, read in reads:
                assert await read.resolve() == index
                assert http.buffer_budget.used >= total

    try:
        task = asyncio.create_task(run())
        await asyncio.wait_for(started.wait(), 2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            await asyncio.wait_for(task, 2)
        assert http.buffer_budget.peak == 2 * total
        assert http.buffer_budget.used == 0
        assert all(r.released for r in reservations)
    finally:
        await http.close()
