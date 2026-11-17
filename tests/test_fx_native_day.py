"""Native daily membership distinguishes a reserved day from a missing history row."""
import copy
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.core.time import CHINA
from empire.features.fx.contract import SYMBOLS, url
from empire.features.fx.source import current_candle
from empire.features.fx.verification import reconcile, verified_snapshot
from tests.test_fx import CODE, collector, source, today_source
from tests.test_fx_verification import CLOSED, CURRENT, NOW, snapshot


@pytest.mark.parametrize('code', SYMBOLS)
async def test_reserved_native_current_day_adjusts_directory_for_all_symbols(code):
    initial = snapshot([CLOSED])
    initial['source_years']['2026'] = initial['years']['2026'] = 2
    c = SimpleNamespace(stats={}, fetch=AsyncMock(side_effect=[(initial, NOW), CURRENT, [CLOSED]]))
    resolved, _, verified = await verified_snapshot(c, code)
    assert resolved['years'] == {'2026': 1} and verified == {2026: [CLOSED]}
    assert resolved['rows'] == [CLOSED] and CURRENT not in resolved['rows']
    assert c.fetch.await_count == 3


def test_exact_223_history_plus_native_current_proves_224_without_fabricating_day():
    # A synthetic fixed date collection exercises counts, not a market calendar.
    start = date(2026, 1, 2)
    rows = [[(start + timedelta(days=i)).isoformat(), '1', '2', '0.5', '1.5']
        for i in range(313) if (start + timedelta(days=i)).weekday() < 5]
    assert len(rows) == 223 and rows[-1][0] == '2026-11-10'
    current = ['2026-11-11', '1.6', '2', '1.5', '1.7']
    initial = dict(start='1974-12-31', end=rows[-1][0], rows=rows[-140:],
        source_tail=rows[-2:], years={'2026': 224}, source_years={'2026': 224})
    result, verified = reconcile(initial, {2026: rows}, datetime(2026, 11, 11, 9, tzinfo=CHINA), current)
    assert verified == {2026: rows} and result['years'] == {'2026': 223}
    assert result['rows'] == rows and result['source_tail'] == [rows[-1], current]


@pytest.mark.parametrize('changes', [{'1': '20261111'}, {'1': '20260230'}, {'1': '2026-11-10'},
    {'7': ''}, {'11': '0'}, {'9': None}, {'open': True}, {'open': 2}])
def test_invalid_native_day_cannot_prove_directory(changes):
    with pytest.raises((ValueError, TypeError)):
        current_candle(today_source(CURRENT, **changes), CODE, NOW)


def test_native_day_identity_jsonp_uniqueness_and_ohlc_mapping():
    assert current_candle(today_source(CURRENT), CODE, NOW) == CURRENT
    assert url(CODE, 'today') == f'https://d.10jqka.com.cn/v6/line/wh_{CODE}/01/today.js'
    for body in (today_source(CURRENT, code='EURUSD'), today_source(CURRENT)[:-1],
        today_source(CURRENT).replace('"open": 1', '"open": 1, "open": 1'),
        today_source(CURRENT).replace('"wh_USDCNH":', '"wh_EURUSD":')):
        with pytest.raises(ValueError):
            current_candle(body, CODE, NOW)
    body = today_source(CURRENT).replace('})', ', "wh_EURUSD": {}})')
    with pytest.raises(ValueError):
        current_candle(body, CODE, NOW)


@pytest.mark.parametrize('count,rows,native', [
    (3, [CLOSED], CURRENT),
    (3, [CLOSED, CURRENT], CURRENT),
    (2, [CLOSED], CLOSED),
    (2, [CLOSED], ['2025-12-31', *CURRENT[1:]]),
    (2, [['2026-11-06', *CLOSED[1:]]], CURRENT),
])
def test_a_numeric_difference_alone_does_not_authorize_missing_closed_days(count, rows, native):
    initial = snapshot([CLOSED])
    initial['source_years']['2026'] = count
    with pytest.raises(ValueError):
        reconcile(initial, {2026: rows}, NOW, native)


async def test_daily_native_protocol_does_not_request_realhead_or_archive_intraday(monkeypatch):
    monkeypatch.setattr('empire.features.fx.transport.datetime', SimpleNamespace(now=lambda _: NOW))
    c = collector()
    def request(method, target, **kwargs):
        assert '/realhead/' not in target
        if target.endswith('today.js'):
            body = today_source(CURRENT)
        elif target.endswith('last.js'):
            body = source(rows=[CLOSED], start='20261109', year={'2026': 2}, total='2')
        else:
            body = source(2026, [CLOSED])
        return httpx.Response(200, content=body.encode())
    c.http.request.side_effect = request
    result = await c.execute()
    assert result['phase'] == 'complete' and c.http.request.await_count == 3
    payload = c.ingest.events[0].raw_payload
    assert payload['rows'] == [CLOSED] and payload['source_count'] == 1
    assert payload['end'] == CLOSED[0]
    c.records.add_error.assert_not_awaited()


async def test_invalid_native_day_preserves_checkpoint_and_is_not_a_source_gap(monkeypatch):
    monkeypatch.setattr('empire.features.fx.transport.datetime', SimpleNamespace(now=lambda _: NOW))
    c = collector()
    original = c.http.request.side_effect
    c.http.request.side_effect = lambda method, target, **kw: (
        httpx.Response(200, content=today_source(CURRENT, **{'11': ''}).encode())
        if target.endswith('today.js') else original(method, target, **kw))
    before = copy.deepcopy(c.ingest.state)
    with pytest.raises(ValueError, match='价格格式'):
        await c.execute()
    assert c.ingest.state == before and not c.ingest.events and c.stats['status'] == 'paused'
    c.records.add_error.assert_awaited_once()
