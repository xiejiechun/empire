"""Listing-directory pages use ordered shared prefetch and retain set proofs."""
import asyncio
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.kaipanla import listings_source as scope
from empire.features.kaipanla.dates import required_days
from tests.prefetch_source import prefetch_http


@pytest.mark.parametrize('announced_date,offset', [(True, 1), (True, 0), (False, 1)])
async def test_announced_listing_attaches_without_requesting_prelisting_days(monkeypatch, announced_date, offset):
    today = datetime.now(scope.CHINA).date()
    tomorrow = today + timedelta(days=offset)
    seen = []

    async def request(method, url, **options):
        seen.append(options['params']['filter'])
        if 'SECUCODE' not in options['params']['filter']:
            return httpx.Response(200, json=dict(success=True, result=dict(count=1, pages=1, data=[
                dict(SECUCODE='000001.SZ', SECURITY_CODE='000001',
                     LISTING_DATE='1991-04-03 00:00:00', LISTING_STATE='0')])))
        return httpx.Response(200, json=dict(success=True, result=dict(count=1, pages=1, data=[
            dict(SECUCODE='920157.BJ', SECURITY_CODE='920157',
                 LISTING_DATE=tomorrow.isoformat()+' 00:00:00' if announced_date else None, LISTING_STATE='9')])))

    collector = SimpleNamespace(http=prefetch_http(request=request), stats={},
        project_id='kaipanla-quote', request_retries=0,
        ingest=SimpleNamespace(admission_wait=AsyncMock()))
    monkeypatch.setattr(scope, 'wait_for_capacity', AsyncMock())
    stocks = await scope.attach_listing_dates(collector, [dict(code='920157', market='BJ')])
    assert seen == ['(LISTING_STATE="0")(SECURITY_TYPE_CODE="058001001")',
                    '(SECUCODE="920157.BJ")']
    if not announced_date:
        assert stocks == [] and collector.stats['unlisted_without_date'] == 1
        return
    stock = stocks[0]
    assert stock['listing_date'] == tomorrow.isoformat()
    assert required_days(stock, [date(2021, 1, 4), today - timedelta(days=1)], set()) == []
    calendar = sorted({today, tomorrow})
    assert required_days(stock, calendar, set()) == [tomorrow]


@pytest.mark.parametrize('state,delta,symbol', [('0', 1, '920157.BJ'), ('9', -1, '920157.BJ'),
    ('9', 32, '920157.BJ'), ('3', 1, '920157.BJ'), ('9', 1, '920157.XX')])
def test_announced_listing_does_not_relax_state_date_or_identity(state, delta, symbol):
    listed = datetime.now(scope.CHINA).date() + timedelta(days=delta)
    payload = dict(success=True, result=dict(count=1, pages=1, data=[
        dict(SECUCODE=symbol, SECURITY_CODE='920157', LISTING_DATE=listed.isoformat()+' 00:00:00',
             LISTING_STATE=state)]))
    with pytest.raises(ValueError):
        scope.parse_listing_page(payload, 1)


@pytest.mark.parametrize('mode', ['cdr', 'different_identity', 'listed_missing_date', 'unknown', 'empty'])
async def test_supplement_requires_exact_source_identity_and_trading_status(mode, monkeypatch):
    async def request(method, url, **options):
        row = dict(SECUCODE='689009.SH', SECURITY_CODE='689009',
                   LISTING_DATE='2020-10-29 00:00:00', LISTING_STATE='0')
        if mode == 'different_identity':
            row.update(SECUCODE='688009.SH', SECURITY_CODE='688009')
        if mode == 'listed_missing_date':
            row['LISTING_DATE'] = None
        if mode == 'unknown':
            row['LISTING_STATE'] = '3'
        payload = dict(success=True, result=dict(count=1, pages=1, data=[row]))
        if mode == 'empty':
            payload = dict(success=False, result=None, code=9201)
        return httpx.Response(200, json=payload)
    c = SimpleNamespace(http=prefetch_http(request=request), stats={},
        project_id='kaipanla-quote', request_retries=0, ingest=SimpleNamespace())
    monkeypatch.setattr(scope, 'wait_for_capacity', AsyncMock())
    response = await scope.download_listing_page(c, 1, supplemental_symbol='689009.SH')
    try:
        if mode == 'cdr':
            assert (await response.consume())[2] == [('689009.SH', date(2020, 10, 29))]
        else:
            with pytest.raises(ValueError):
                await response.consume()
    finally:
        response.close()


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
