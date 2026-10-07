"""Listing-directory pages use ordered shared prefetch and retain set proofs."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.plugins.collectors import kaipanla_scope as scope
from tests.prefetch_source import prefetch_http


@pytest.mark.parametrize('mode', ['success', 'duplicate', 'cancel'])
async def test_listing_directory_out_of_order_and_cleanup(mode, monkeypatch):
    release, third = asyncio.Event(), asyncio.Event()
    parsed, responses = [], []
    original = scope.parse_listing_page

    def parse(payload, page):
        parsed.append(page)
        return original(payload, page)

    monkeypatch.setattr(scope, 'parse_listing_page', parse)

    async def request(method, url, **kwargs):
        page = int(kwargs['params']['pageNumber'])
        if page == 2:
            await release.wait()
        rows = [dict(SECUCODE=f'{i:06d}.SH', SECURITY_CODE=f'{i:06d}',
                     LISTING_DATE='2020-01-01 00:00:00', LISTING_STATE='0')
                for i in range((page - 1) * 500 + 1, min(page * 500, 1001) + 1)]
        if page == 3 and mode == 'duplicate':
            rows[0].update(SECUCODE='001000.SH', SECURITY_CODE='001000')
        response = httpx.Response(200, json=dict(success=True,
            result=dict(count=1001, pages=3, data=rows)))
        responses.append(response)
        if page == 3:
            third.set()
        return response

    http = prefetch_http(request=request)
    http.parallelism.return_value = 2
    collector = SimpleNamespace(http=http, stats={}, project_id='kaipanla-trend',
        request_retries=0, ingest=SimpleNamespace(admission_wait=AsyncMock()))
    monkeypatch.setattr(scope, 'wait_for_capacity', AsyncMock())
    task = asyncio.create_task(scope.attach_listing_dates(collector,
        [dict(code='001001', market='SH')]))
    await asyncio.wait_for(third.wait(), 3)
    assert parsed == [1]
    assert http.buffer_budget.used > 0
    if mode == 'cancel':
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        release.set()
        if mode == 'duplicate':
            with pytest.raises(ValueError, match='重复'):
                await task
        else:
            assert (await task)[0]['listing_date'] == '2020-01-01'
        assert parsed == [1, 2, 3]
    assert http.buffer_budget.used == 0
    assert all(response.is_closed for response in responses)
