"""Explicit empty heads are availability gaps, never fabricated prices."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.contracts.collector import CollectionSourceGap
from empire.features.fx.contract import SYMBOLS
from empire.features.fx.live import FxLiveCollector
from empire.features.fx.source import QuoteUnavailable, realtime
from tests.prefetch_source import prefetch_http
from tests.test_fx import NOW, collector, live_source


def empty(code='USDCNY', **changes):
    return live_source(code, **({'10': '', '7': '', '8': '', '9': ''} | changes))


@pytest.mark.parametrize('code', SYMBOLS)
@pytest.mark.parametrize('previous', ['', '6.6805'])
def test_explicit_empty_prices_for_every_symbol(code, previous):
    with pytest.raises(QuoteUnavailable, match=code):
        realtime(empty(code, **{'6': previous}), code, NOW)


@pytest.mark.parametrize('changes', [
    {'10': '6'}, {'7': None}, {'8': 0}, {'9': '--'}, {'6': None},
    {'6': '0'}, {'6': 'NaN'}, {'marketid': '98'}, {'5': 'USDCHF'},
    {'time': 'bad'}, {'updateTime': '2027-01-01 00:00'},
])
def test_malformed_head_is_never_unavailable(changes):
    with pytest.raises(ValueError) as error:
        realtime(empty(**changes), 'USDCNY', NOW)
    assert not isinstance(error.value, QuoteUnavailable)


@pytest.mark.parametrize('field', ['10', '7', '8', '9', '6', 'time', 'updateTime'])
def test_missing_fields_are_never_unavailable(field):
    body = empty()
    callback, payload = body.split('(', 1)
    data = json.loads(payload[:-1])
    del data['items'][field]
    with pytest.raises(ValueError) as error:
        realtime(callback + '(' + json.dumps(data) + ')', 'USDCNY', NOW)
    assert not isinstance(error.value, QuoteUnavailable)


def live_collector():
    c, helper = FxLiveCollector(), collector()
    c.selected_codes = ['USDCNY', 'EURUSD']
    c.records = helper.records
    c.store = SimpleNamespace(save=AsyncMock())
    class Admission:
        stats = {}
        ensure_capacity = AsyncMock()
        async def capacity_status(self):
            return {'blocked': False}
        async def publish_volatile(self, project, commit):
            return await commit()
    c.ingest = Admission()
    return c


async def test_live_continues_after_empty_then_recovers_without_extra_requests():
    c = live_collector()
    def response(method, url, **kwargs):
        code = url.split('wh_')[1].split('/')[0]
        return httpx.Response(200, content=(empty(code) if code == 'USDCNY' else live_source(code)).encode())
    c.http = prefetch_http(request=AsyncMock(side_effect=response))
    with pytest.raises(CollectionSourceGap, match='USDCNY'):
        await c.execute()
    assert c.http.request.await_count == 2
    assert c.store.save.await_count == 1
    assert c.store.save.call_args.args[0]['symbol'] == 'EURUSD'
    assert c.stats['completed_units'] == 2 and c.stats['collected'] == 1
    assert c.stats['status'] == 'source_gap'
    c.records.add_error.assert_not_awaited()
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200,
        content=live_source(url.split('wh_')[1].split('/')[0]).encode())
    assert (await c.execute())['collected'] == 2
    assert c.stats['unavailable_codes'] == [] and c.stats['notice'] == ''
    assert c.http.request.await_count == 4


async def test_all_unavailable_round_does_not_claim_complete():
    c = live_collector()
    c.http = prefetch_http(request=AsyncMock(side_effect=lambda method, url, **kw:
        httpx.Response(200, content=empty(url.split('wh_')[1].split('/')[0]).encode())))
    with pytest.raises(CollectionSourceGap, match='0/2'):
        await c.execute()
    c.store.save.assert_not_awaited()
    assert c.stats['unavailable_codes'] == c.selected_codes
    c.records.add_error.assert_not_awaited()


async def test_daily_unrelated_quote_cannot_substitute_native_day_validation():
    c = collector()
    original = c.http.request.side_effect
    c.http.request.side_effect = lambda method, url, **kw: (
        httpx.Response(200, content=empty('USDCNH').encode()) if '/today.js' in url
        else original(method, url, **kw))
    with pytest.raises(ValueError, match='JSONP身份不符'):
        await c.execute()
    assert not c.ingest.events
    c.records.add_error.assert_awaited_once()
