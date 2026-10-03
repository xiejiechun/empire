import asyncio
import copy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.plugins.collectors.kaipanla_intraday import KaipanlaIntradayCollector
from empire.plugins.collectors.kaipanla_scope import lifecycle, parse_listing_page, required_days
from empire.plugins.datasets.intraday import validate
from empire.plugins.infra.http import HttpService
from tests.test_http import MemoryPermits
from tests.test_kaipanla_source import sample

STOCK = dict(market='SZ', code='000001', name='样本', listing_date='1991-04-03')


def listing():
    return dict(success=True, result=dict(count=1, pages=1, data=[
        dict(SECUCODE='000001.SZ', SECURITY_CODE='000001', LISTING_DATE='1991-04-03 00:00:00', LISTING_STATE='0')]))


def row(day='2021-01-04'):
    return dict(market='SZ', code='000001', trade_date=day, preclose_px=10,
                trend=sample('trend')['trend'], auction=sample('auction')['bid'],
                source_times=[1609743727, 1609723596], lifecycle=lifecycle(STOCK),
                source_codes=['000001', '000001'], aliases={})


class Publisher:
    def __init__(self):
        self.state = dict(revision=0, cursor={})
        self.published = []
        self.ensure_capacity = AsyncMock()

    async def checkpoint(self, job):
        return copy.deepcopy(self.state)

    async def publish_page(self, envelopes, *, expected_revision, cursor, **kwargs):
        assert self.state['revision'] == expected_revision
        self.published.extend(envelopes)
        self.state = dict(revision=expected_revision + 1, cursor=copy.deepcopy(cursor))
        return copy.deepcopy(self.state)

    async def advance_checkpoint(self, *, expected_revision, cursor, **kwargs):
        assert self.state['revision'] == expected_revision
        self.state = dict(revision=expected_revision + 1, cursor=copy.deepcopy(cursor))
        return copy.deepcopy(self.state)


def collector(days=None):
    c = KaipanlaIntradayCollector()
    days = days or [date(2021, 1, 4), date(2021, 1, 5)]
    c.ingest = Publisher()
    c.query = SimpleNamespace(plan=AsyncMock(return_value=([STOCK], days)),
        covered_days=AsyncMock(return_value=set()), suspended_days=AsyncMock(return_value=set()))
    c.records = SimpleNamespace(add_error=AsyncMock(), sanitize_text=str)
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    async def request(method, url, **options):
        if 'eastmoney.com' in url:
            return httpx.Response(200, json=listing())
        data = options['attempt_options']()['data']
        kind = 'trend' if data['a'] == 'GetStockTrend' else 'auction'
        body = sample(kind)
        body['day'] = data['Day'].replace('-', '')
        return httpx.Response(200, json=body)
    c.http = SimpleNamespace(request=AsyncMock(side_effect=request), response_policy=lambda _: None)
    return c


def test_listing_exact_identity_and_pagination_contract():
    total, pages, rows = parse_listing_page(listing(), 1)
    assert total == pages == len(rows) == 1
    bad = listing()
    bad['result']['count'] = 501
    with pytest.raises(ValueError):
        parse_listing_page(bad, 1)
    bad = listing()
    bad['result']['data'][0]['LISTING_STATE'] = '3'
    with pytest.raises(ValueError):
        parse_listing_page(bad, 1)


def test_listing_bse_market_and_suspension_boundaries():
    days = [date(2021, 1, 4), date(2021, 11, 15), date(2024, 5, 30)]
    bj = dict(market='BJ', code='920000', listing_date='2020-12-23')
    assert required_days(bj, days, set()) == days[1:]
    bj['listing_date'] = '2024-05-30'
    assert required_days(bj, days, set()) == days[-1:]
    assert required_days(STOCK, days, {days[0]}) == days[1:]


def test_required_lifecycle_and_full_minute_set_are_not_optional():
    good = row()
    validate(good)
    good['trend'][1] = good['trend'][0][:]
    with pytest.raises(ValueError):
        validate(good)
    broken = row()
    del broken['lifecycle']
    with pytest.raises(ValueError):
        validate(broken)


async def test_two_days_queued_before_archive_confirmation():
    c = collector()
    async def confirm(*args):
        assert len(c.ingest.published) == 2
        assert c.http.request.await_count == 5  # One lifecycle page + each response once.
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    result = await c.execute()
    assert result['phase'] == 'complete' and result['index'] == 2
    assert len(c.ingest.published[0].raw_payload['rows'][0]['auction']) == 5
    assert 'DeviceID' not in str(c.ingest.state)


async def test_failure_does_not_advance_failed_unit_and_resume_does_not_wait_old_archive():
    c = collector()
    original = c.http.request.side_effect
    async def fail(method, url, **options):
        if 'attempt_options' in options and options['attempt_options']()['data']['Day'] == '2021-01-05':
            return httpx.Response(200, json={'errcode': '1020'})
        return await original(method, url, **options)
    c.http.request.side_effect = fail
    with pytest.raises(ValueError):
        await c.execute()
    assert c.ingest.state['cursor']['index'] == 1 and len(c.ingest.published) == 1
    c.confirmation.page_status.assert_awaited_once()  # Only after all download attempts ended.
    c.http.request.side_effect = original
    result = await c.execute()
    assert result['phase'] == 'complete' and len(c.ingest.published) == 2


async def test_sql_missing_midday_recovers_after_redis_loss_and_recent_days_refresh():
    days = [date(2021, 1, d) for d in range(4, 12)]
    c = collector(days)
    c.query.covered_days.return_value = set(days) - {days[1]}
    result = await c.execute()
    assert result['phase'] == 'complete'
    dates = [e.raw_payload['rows'][0]['trade_date'] for e in c.ingest.published]
    assert dates == [days[1].isoformat(), *(d.isoformat() for d in days[-5:])]
    assert c.query.covered_days.call_args.args[-1] == lifecycle(STOCK)


async def test_cancel_awaiting_archive_resumes_without_source_calls():
    c = collector()
    c.confirmation.page_status.return_value = None
    task = asyncio.create_task(c.execute())
    for _ in range(100):
        if c.stats['status'] == 'awaiting_archive':
            break
        await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    count = c.http.request.await_count
    c.confirmation.page_status.return_value = {'status': 'complete'}
    await c.execute(fresh=True)
    assert c.http.request.await_count == count


async def test_middle_source_gap_keeps_frontier_and_archives_later_valid_day():
    days = [date(2021, 1, 4), date(2021, 1, 5), date(2021, 1, 6)]
    c = collector(days)
    original = c.http.request.side_effect
    async def request(method, url, **options):
        if 'attempt_options' in options and options['attempt_options']()['data']['Day'] == '2021-01-05':
            return httpx.Response(200, json={'errcode': '1017'})
        return await original(method, url, **options)
    c.http.request.side_effect = request
    with pytest.raises(ValueError, match='仍有来源缺口'):
        await c.execute()
    assert [e.raw_payload['rows'][0]['trade_date'] for e in c.ingest.published] == ['2021-01-04', '2021-01-06']
    assert c.ingest.state['cursor']['index'] == 1
    assert c.ingest.state['cursor']['first_gap']['trade_date'] == '2021-01-05'
    assert c.stats['status'] == 'error'
    assert c.ingest.state['cursor']['phase'] == 'collecting'


async def test_transport_retry_gets_new_device_and_keeps_shared_permits():
    from empire.plugins.collectors.kaipanla_source import request_options
    seen = []
    async def respond(request):
        from urllib.parse import parse_qs
        seen.append(parse_qs(request.content.decode())['DeviceID'][0])
        if len(seen) == 1:
            raise httpx.ConnectError('test connection failure', request=request)
        return httpx.Response(200, json={'ok': True})
    permits = MemoryPermits()
    service = HttpService(permits, 'test', {'kaipanla': {'domains': ['longhuvip.com'], 'min_interval_ms': 1}},
                          transport=httpx.MockTransport(respond))
    try:
        response = await service.request('POST', 'https://apphis.longhuvip.com/w1/api/index.php',
            allowed_domains=('longhuvip.com',), max_retries=1, max_redirects=0,
            attempt_options=lambda: request_options('000001', date(2021, 1, 4), 'trend'))
        response.close()
        assert len(seen) == 2 and seen[0] != seen[1]
        assert len(permits.permits) == 2
    finally:
        await service.close()


async def test_legacy_code_needs_exchange_proof_and_releases_budget_before_lookup():
    import json

    from empire.plugins.collectors.kaipanla_source import fetch_day
    calls = []
    async def respond(request):
        calls.append(request.url.host)
        if request.url.host == 'www.bse.cn':
            page = dict(totalElements=1, content=[dict(xxzqdm='920000', xxfcbj='2',
                xxisin='CNE1000048X1', fxssrq='20201223')])
            return httpx.Response(200, content=('securityMasterCallback(' + json.dumps([page]) + ');').encode())
        kind = 'auction' if b'GetStockBid' in request.content else 'trend'
        payload = sample(kind)
        payload.update(code='832000' if kind == 'auction' else '920000', day=20211115)
        return httpx.Response(200, json=payload)
    permits = MemoryPermits()
    service = HttpService(permits, 'test', {
        'kaipanla': {'domains': ['longhuvip.com'], 'min_interval_ms': 1},
        'bse': {'domains': ['bse.cn'], 'min_interval_ms': 1}},
        transport=httpx.MockTransport(respond),
        resources=dict(generic_response_bytes=16384, buffer_budget_bytes=3 * 16384 + 262144))
    c = collector()
    c.http = service
    try:
        data = await asyncio.wait_for(fetch_day(c, '920000', date(2021, 11, 15), 'BJ', '2020-12-23'), 2)
        assert data['source_codes'] == ['920000', '832000']
        assert data['aliases']['832000']['current_code'] == '920000'
        assert calls == ['apphis.longhuvip.com', 'apphis.longhuvip.com', 'www.bse.cn']
        assert service.buffer_budget.used == 0
        # This proof is cached only within the current download round.
        await fetch_day(c, '920000', date(2021, 11, 15), 'BJ', '2020-12-23')
        assert calls.count('www.bse.cn') == 1
    finally:
        await service.close()


def test_wrong_exchange_mapping_never_authorizes_a_foreign_security():
    import json

    from empire.plugins.collectors.kaipanla_alias import parse_alias
    page = dict(totalElements=1, content=[dict(xxzqdm='920001', xxfcbj='2',
        xxisin='CNE1000048X1', fxssrq='20201223')])
    with pytest.raises(ValueError):
        parse_alias('securityMasterCallback(' + json.dumps([page]) + ');', '920000', '832000', '2020-12-23')


def test_arbitrary_legacy_header_cannot_be_normalized_without_identity_evidence():
    data = row()
    data['source_codes'][1] = '832000'
    with pytest.raises(ValueError):
        validate(data)


def test_future_security_day_cannot_authorize_a_cache_or_archive_proof():
    from datetime import timedelta
    data = row()
    data['trade_date'] = (date.today() + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError):
        validate(data)
