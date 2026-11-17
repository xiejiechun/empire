"""Shared download path, single-read budgets and cancellation ownership."""

import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.graymarket.download import GraymarketDownload
from empire.features.graymarket.source import DOMAINS, URL
from tests.prefetch_source import prefetch_http
from tests.test_graymarket import parsed, response


def reader(total=101):
    owner = GraymarketDownload()
    owner.stats = {}
    owner.request_retries = 2
    owner.ingest = SimpleNamespace(ensure_capacity=AsyncMock())
    owner.records = SimpleNamespace(add_error=AsyncMock())
    responses = []

    async def request(method, url, **kwargs):
        assert method == "GET" and url == URL
        assert kwargs["allowed_domains"] == DOMAINS
        assert kwargs["project_id"] == "eastmoney-graymarket"
        assert kwargs["max_retries"] == 2
        page = kwargs["params"]["StartPage"]
        result = httpx.Response(200, content=json.dumps(response(total, page), default=str).encode())
        responses.append(result)
        return result

    owner.http = prefetch_http(request=AsyncMock(side_effect=request))
    return owner, responses


async def test_single_read_budget_and_response_release():
    owner, responses = reader()
    async with owner.daily_reads(["2026-11-02"]) as reads:
        async for _, read in reads:
            rows, observed = await read.resolve()
            assert len(rows) == 101 and observed.tzinfo is UTC
            assert owner.http.buffer_budget.used > 0
    assert owner.http.request.call_count == 2
    assert owner.http.buffer_budget.used == 0
    assert all(r.is_closed for r in responses)


async def test_discovery_page_reused_without_new_observation_version():
    owner, _ = reader()
    observed = datetime(2026, 11, 2, 10, tzinfo=UTC)
    first = parsed(response())
    async with owner.daily_reads(["2026-11-02"], discovered=(first, observed)) as reads:
        async for _, read in reads:
            rows, version = await read.resolve()
            assert len(rows) == 101 and version == observed
    assert owner.http.request.call_count == 1
    assert owner.http.request.call_args.kwargs["params"]["StartPage"] == 2
    assert owner.http.buffer_budget.used == 0


async def test_invalid_page_fails_day_and_stops_later_requests():
    owner, responses = reader(total=301)
    original = owner.http.request.side_effect

    async def broken(method, url, **kw):
        if kw["params"]["StartPage"] == 2:
            result = httpx.Response(200, json={"errid": -2, "errmsg": "no data"})
            responses.append(result)
            return result
        return await original(method, url, **kw)

    owner.http.request.side_effect = broken
    with pytest.raises(ValueError, match="有效数据"):
        async with owner.daily_reads(["2026-11-02"]) as reads:
            async for _, read in reads:
                await read.resolve()
    assert owner.http.request.call_count == 2
    assert owner.http.buffer_budget.used == 0
    assert all(r.is_closed for r in responses)
    assert owner.records.add_error.call_count == 1


async def test_cancel_during_next_page_releases_retained_day():
    owner, responses = reader(total=301)
    original = owner.http.request.side_effect
    started = asyncio.Event()

    async def stalled(method, url, **kw):
        if kw["params"]["StartPage"] == 2:
            started.set()
            await asyncio.Future()
        return await original(method, url, **kw)

    owner.http.request.side_effect = stalled

    async def consume():
        async with owner.daily_reads(["2026-11-02"]) as reads:
            async for _, read in reads:
                await read.resolve()

    task = asyncio.create_task(consume())
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert owner.http.buffer_budget.used == 0
    assert all(r.is_closed for r in responses)


async def test_early_consumer_exit_releases_retained_day():
    owner, _ = reader(total=1)
    async with owner.daily_reads(["2026-11-02", "2026-11-03"]) as reads:
        async for _, read in reads:
            await read.resolve()
            break
    assert owner.http.buffer_budget.used == 0
    assert owner.http.request.call_count == 1
