"""Cross-day epochs stay invalid; live recovery shares the transport budget."""
import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.core.time import CHINA
from empire.features.yuanhang_limits.collector import LimitCollector
from empire.features.yuanhang_limits.contract import POOLS, TIME_FIELDS
from empire.features.yuanhang_limits.model import SourceTimeDateError, member
from empire.features.yuanhang_limits.source import earlier_pool_time, fetch_pool
from empire.plugins.infra.http import HttpService
from tests.test_http import ErrorRecorder, MemoryPermits
from tests.test_yuanhang_limits_source import client, page, row


def timed_row(field, day='2026-07-14', code='000001'):
    value = row(code)
    value[field] = str(int(datetime.fromisoformat(day + 'T09:30:00').replace(tzinfo=CHINA).timestamp()))
    return value


@pytest.mark.parametrize('field', TIME_FIELDS)
def test_observed_invalid_time_preserves_source_value(field):
    from empire.features.yuanhang_limits.storage import validate_member
    value = member({**row('603729'), field: '-60'}, '2026-07-15')
    assert value[field] == -60
    assert validate_member(value, '2026-07-15') == value
    for field, raw in [(field, '-1'), (field, '-61'), (field, -60), (field, '-060')]:
        with pytest.raises(ValueError):
            member({**row(), field: raw}, '2026-07-15')


@pytest.mark.parametrize('field', TIME_FIELDS)
@pytest.mark.parametrize('code', ['000001', '300010'])
def test_every_time_field_and_security_keeps_original_date(field, code):
    with pytest.raises(SourceTimeDateError) as caught:
        member(timed_row(field, code=code), '2026-07-15')
    meta = caught.value.source_metadata
    assert meta['field'] == field and meta['unified_code'] == code + '.SZ'
    assert meta['trade_date'] == '2026-07-15' and meta['source_date'] == '2026-07-14'
    assert meta['source_datetime'] == '2026-07-14T09:30:00+08:00'
    assert str(int(datetime.fromisoformat(meta['source_datetime']).timestamp())) == meta['source_seconds']


@pytest.mark.parametrize('body,expected', [
    (page([timed_row('first_limit_up_time')]), True),
    (page([timed_row('first_limit_up_time', '2026-07-16')]), False),
    (page([row()]), False), (page([]), False),
    (page([{**row(), 'first_limit_up_time': '0'}]), False),
    (page([{**row(), 'first_limit_up_time': None}]), False),
    (page([{**row(), 'first_limit_up_time': 'n/a'}]), False),
    (page([{**row(), 'first_limit_up_time': '99999999999999999999'}]), False),
    (page([timed_row('first_limit_up_time')], total=2), False),
    ({'status_code': -1}, False), ([], False),
])
def test_live_retry_is_limited_to_detected_earlier_epoch(body, expected):
    assert earlier_pool_time(SimpleNamespace(content=json.dumps(body).encode()),
                             day='2026-07-15', page=1) is expected
    assert not earlier_pool_time(SimpleNamespace(content=b'{broken'), day='2026-07-15', page=1)


@pytest.mark.parametrize('pool', POOLS)
async def test_exhausted_page_diagnostic_keeps_time_context_and_body(pool):
    http, responses = client(page([timed_row('first_limit_up_time')]))
    with pytest.raises(SourceTimeDateError) as caught:
        await fetch_pool(http, pool, '2026-07-15', project_id='test', retry_earlier_time=True)
    error = caught.value
    assert error.source_metadata['pool_type'] == pool and error.source_metadata['page'] == 1
    assert error.source_diagnostic['raw_body'] == responses[0].content
    assert error.source_diagnostic['metadata']['source_date'] == '2026-07-14'
    assert error.source_diagnostic['status_code'] == 200
    responses[0].close.assert_called_once()


@pytest.mark.parametrize('live,budget,recover,transport,attempts', [
    (True, 2, True, False, 2), (True, 2, False, False, 3),
    (True, 2, True, True, 3), (True, 1, False, True, 2),
    (True, 0, False, False, 1), (False, 2, False, False, 1),
    (True, 5, True, True, 6),
])
async def test_fetch_recovery_or_exhaustion_uses_one_shared_budget(
        monkeypatch, live, budget, recover, transport, attempts):
    service = HttpService(MemoryPermits(), 'test',
        {'ths': {'domains': ['10jqka.com.cn'], 'min_interval_ms': 1}}, records=ErrorRecorder())
    responses, delays = [], []

    async def one(method, url, domains, **kwargs):
        index = len(responses)
        status = 503 if transport and index == 0 else 200
        body = page([row() if recover and index == attempts - 1 else timed_row('first_limit_up_time')])
        response = httpx.Response(status, request=httpx.Request(method, url), json=body)
        responses.append(response)
        return response

    async def sleep(delay):
        delays.append(delay)

    monkeypatch.setattr(service, '_one', one)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    # The real shared request/retry implementation is used, with only transport replaced.
    http = SimpleNamespace(request=service._request, response_policy=service.response_policy)
    try:
        if recover:
            result = await fetch_pool(http, 'limit_up_pool', '2026-07-15', project_id='test',
                                     max_retries=budget, retry_earlier_time=live)
            assert result['rows'] == [member(row(), '2026-07-15')]
        else:
            with pytest.raises(SourceTimeDateError):
                await fetch_pool(http, 'limit_up_pool', '2026-07-15', project_id='test',
                                 max_retries=budget, retry_earlier_time=live)
        assert len(responses) == attempts and delays == [min(30, 2 ** i) for i in range(attempts - 1)]
        assert all(response.is_closed for response in responses)
        assert service.buffer_budget.used == 0
    finally:
        await service.close()


async def test_live_failure_reaches_recording_without_snapshot_or_checkpoint_changes(monkeypatch):
    from empire.features.yuanhang_limits import intraday
    from tests.test_yuanhang_limits_collector import setup_collector

    c, state, events, _ = setup_collector(['2026-07-15'])
    c.intraday = True
    http, responses = client(page([timed_row('first_limit_up_time')]))
    c.http.request = http.request
    c.fetch = LimitCollector.fetch.__get__(c)
    c.live_store = SimpleNamespace(save=AsyncMock())
    monkeypatch.setattr(intraday, 'phase', AsyncMock(return_value='live'))
    with pytest.raises(SourceTimeDateError):
        await c.execute()
    assert state == {'revision': 0, 'cursor': {}} and not events
    c.live_store.save.assert_not_awaited()
    c.confirmation.page_status.assert_not_awaited()
    diagnostic = c.records.add_error.call_args.kwargs
    assert diagnostic['metadata']['source_date'] == '2026-07-14'
    assert diagnostic['raw_body'] == responses[0].content
    assert c.http.request.call_args.kwargs['retry_response'] is not None


async def test_cross_page_failure_retains_failing_page_diagnostic():
    http, responses = client(page([row(f'{i:06}') for i in range(1, 101)], 101),
                             page([row('000101'), row('000102')], 102, 2))
    with pytest.raises(ValueError, match='跨页总量') as caught:
        await fetch_pool(http, 'limit_up_pool', '2026-07-15', project_id='test')
    assert caught.value.source_metadata['page'] == 2
    assert caught.value.source_diagnostic['raw_body'] == responses[1].content
    assert all(response.close.call_count == 1 for response in responses)
