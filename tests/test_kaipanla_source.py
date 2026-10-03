"""Lossless source semantics; samples are synthetic, not stored successful responses."""
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.plugins.collectors.kaipanla_source import (
    TREND_TIMES,
    SourceError,
    combine_day,
    fetch_day,
    parse_response,
    request_options,
)

DAY = date(2021, 1, 4)


def sample(kind):
    rows = [[clock, 10, 10, 2, 0] for clock in TREND_TIMES] if kind == 'trend' else [
        ['09:15', 10, 0, 10], ['09:15', 10.1, 1, 20],
        ['09:15', 10.1, 1, 20], ['09:16', 10, 0, 5], ['09:24', 10, 1, 8]]
    return dict(code='000001', day=20210104, time=1609743727, preclose_px=10,
                errcode='0', **{('trend' if kind == 'trend' else 'bid'): rows})


def test_anonymous_identity_varies_without_account_or_token():
    requests = [request_options('000001', DAY, 'trend') for _ in range(100)]
    assert len({r['data']['DeviceID'] for r in requests}) == 100
    assert all(set(r['data']) == {'c', 'a', 'StockID', 'Day', 'apiv', 'PhoneOSNew',
                                 'PhoneOS', 'DeviceID', 'VerSion'} for r in requests)


def test_all_auction_points_and_volume_decreases_survive():
    auction = parse_response(sample('auction'), '000001', DAY, 'auction')
    trend = parse_response(sample('trend'), '000001', DAY, 'trend')
    data = combine_day(trend, auction)
    assert data['auction'] == sample('auction')['bid']
    assert len(data['auction']) == 5  # Same minute and identical points remain separate.
    assert data['auction'][3][3] == 5  # Never differenced or clamped.
    assert data['trend'][-1][0] == '15:00'


def test_equal_count_different_minute_keys_rejected():
    payload = sample('trend')
    payload['trend'][1] = payload['trend'][0][:]
    assert len(payload['trend']) == 241
    with pytest.raises(SourceError, match='分钟键集合'):
        parse_response(payload, '000001', DAY, 'trend')


@pytest.mark.parametrize('change', [dict(code='600519'), dict(day=20210105),
    dict(errcode='1020'), dict(trend=[]), dict(time=None), dict(preclose_px=0)])
def test_wrong_identity_errors_and_empty_are_not_coverage(change):
    with pytest.raises(SourceError):
        parse_response({**sample('trend'), **change}, '000001', DAY, 'trend')


@pytest.mark.parametrize('row', [['09:14', 10, 0, 1], ['09:16', float('nan'), 0, 1],
    ['09:16', 10, 0, -1], ['09:16', 10, True, 1], ['09:16', 10, 0]])
def test_auction_bad_fields_rejected(row):
    payload = sample('auction')
    payload['bid'] = [row]
    with pytest.raises(SourceError):
        parse_response(payload, '000001', DAY, 'auction')


def test_conflicting_two_responses_rejected():
    trend = parse_response(sample('trend'), '000001', DAY, 'trend')
    auction = parse_response({**sample('auction'), 'preclose_px': 11}, '000001', DAY, 'auction')
    with pytest.raises(SourceError, match='冲突'):
        combine_day(trend, auction)


@pytest.mark.asyncio
async def test_shared_download_once_per_part_closes_and_keeps_all_points():
    import json
    responses = [SimpleNamespace(content=json.dumps(sample(kind)).encode(), close=AsyncMock(), status_code=200)
                 for kind in ('trend', 'auction')]
    # Production response.close is synchronous; keep explicit close counters.
    closed = []
    for index, response in enumerate(responses):
        response.close = lambda i=index: closed.append(i)
    collector = SimpleNamespace(ingest=SimpleNamespace(ensure_capacity=AsyncMock()), stats={},
        http=SimpleNamespace(request=AsyncMock(side_effect=responses), response_policy=lambda p: p),
        records=SimpleNamespace(add_error=AsyncMock()), project_id='kaipanla-intraday', request_retries=2)
    result = await fetch_day(collector, '000001', DAY)
    assert result['auction'] == sample('auction')['bid']
    assert closed == [0, 1]
    calls = collector.http.request.call_args_list
    assert len(calls) == 2
    assert calls[0].kwargs['attempt_options']()['data']['DeviceID'] != calls[1].kwargs['attempt_options']()['data']['DeviceID']
    assert all(c.kwargs['max_redirects'] == 0 for c in calls)
    assert all(c.kwargs['allowed_domains'] == ('longhuvip.com',) for c in calls)
    assert all(c.kwargs['max_retries'] == 2 for c in calls)


@pytest.mark.asyncio
async def test_source_failure_closes_response_without_retry_or_checkpoint():
    response = SimpleNamespace(content=b'{"errcode":"1020"}', status_code=200)
    closed = []
    response.close = lambda: closed.append(True)
    collector = SimpleNamespace(ingest=SimpleNamespace(ensure_capacity=AsyncMock()), stats={},
        http=SimpleNamespace(request=AsyncMock(return_value=response), response_policy=lambda p: p),
        records=SimpleNamespace(add_error=AsyncMock()), project_id='kaipanla-intraday', request_retries=2)
    with pytest.raises(SourceError):
        await fetch_day(collector, '000001', DAY)
    assert closed == [True]
    assert collector.http.request.await_count == 1
    collector.records.add_error.assert_awaited_once()
