"""Native daily empty OHLC is an availability gap for every registered symbol."""
import copy
import json

import httpx
import pytest

from empire.contracts.collector import CollectionSourceGap
from empire.features.fx.contract import SYMBOLS
from empire.features.fx.source import current_candle
from tests.test_fx import CODE, today_source
from tests.test_fx_source_gaps import CODES, gap_collector
from tests.test_fx_verification import CURRENT, NOW

PRICE_FIELDS = ('7', '8', '9', '11')


def empty_day(code=CODE, **changes):
    return today_source(CURRENT, code=code, **(dict.fromkeys(PRICE_FIELDS, '') | changes))


@pytest.mark.parametrize('code', SYMBOLS)
@pytest.mark.parametrize('open_state', [0, 1])
def test_valid_empty_day_has_specific_availability_type(code, open_state):
    from empire.features.fx.source import DailyQuoteUnavailable
    with pytest.raises(DailyQuoteUnavailable, match=code):
        current_candle(empty_day(code, open=open_state), code, NOW)


@pytest.mark.parametrize('field', PRICE_FIELDS)
@pytest.mark.parametrize('value', [None, 0, '--', '0', 'NaN', '6.5'])
def test_partial_empty_or_invalid_price_is_not_availability(field, value):
    from empire.features.fx.source import DailyQuoteUnavailable
    with pytest.raises(ValueError) as error:
        current_candle(empty_day(**{field: value}), CODE, NOW)
    assert not isinstance(error.value, DailyQuoteUnavailable)


@pytest.mark.parametrize('field', [*PRICE_FIELDS, '1', 'open'])
def test_missing_fields_are_not_availability(field):
    from empire.features.fx.source import DailyQuoteUnavailable
    callback, raw = empty_day().split('(', 1)
    value = json.loads(raw[:-1])
    del value['wh_' + CODE][field]
    with pytest.raises(ValueError) as error:
        current_candle(callback + '(' + json.dumps(value) + ')', CODE, NOW)
    assert not isinstance(error.value, DailyQuoteUnavailable)


@pytest.mark.parametrize('changes', [{'1': '20261112'}, {'1': '20260230'}, {'open': True}, {'open': 2}])
def test_invalid_day_or_state_is_not_availability(changes):
    from empire.features.fx.source import DailyQuoteUnavailable
    with pytest.raises(ValueError) as error:
        current_candle(empty_day(**changes), CODE, NOW)
    assert not isinstance(error.value, DailyQuoteUnavailable)


def daily_empty_collector(monkeypatch, failures):
    c, _ = gap_collector(monkeypatch, None)
    original = c.http.request.side_effect
    def response(method, url, **kwargs):
        code = url.split('wh_')[1].split('/')[0]
        if '/today.js' in url and code in failures:
            return httpx.Response(200, content=empty_day(code).encode())
        return original(method, url, **kwargs)
    c.http.request.side_effect = response
    return c


@pytest.mark.parametrize('failures', [{code} for code in CODES] + [set(CODES), set(CODES[:2])])
async def test_empty_day_keeps_first_gap_archives_siblings_and_recovers(monkeypatch, failures):
    c = daily_empty_collector(monkeypatch, failures)
    missing = set(failures)
    async def confirm(*args):
        assert {e.raw_payload['code'] for e in c.ingest.events} == set(CODES) - missing
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    with pytest.raises(CollectionSourceGap, match='当日日线暂无报价'):
        await c.execute()
    cursor = c.ingest.state['cursor']
    if missing == set(CODES):
        assert cursor == {} and c.ingest.state['revision'] == 0
    else:
        assert cursor['next_index'] == min(CODES.index(code) for code in missing)
        assert cursor['phase'] == 'collecting' and cursor['pages'] == len(CODES) - len(missing)
    assert c.stats['completed_units'] == len(CODES) - len(missing)
    assert c.stats['status'] == 'source_gap'
    assert c.http.request.await_count == 2 * len(CODES) + len(CODES) - len(missing)
    # Empty symbols use last+today only, never a retry or an annual fallback.
    for code in missing:
        requests = [call.args[1] for call in c.http.request.await_args_list if 'wh_' + code + '/' in call.args[1]]
        assert len(requests) == 2 and all(url.endswith(('last.js', 'today.js')) for url in requests)
    c.records.add_error.assert_not_awaited()
    c.confirmation.page_status.side_effect = None
    c.confirmation.page_status.return_value = {'status': 'complete'}
    failures.clear()
    assert (await c.execute())['phase'] == 'complete'
    assert c.stats['unavailable_codes'] == [] and c.stats['notice'] == ''


async def test_empty_day_does_not_hide_archive_failure(monkeypatch):
    c = daily_empty_collector(monkeypatch, {CODES[1]})
    c.confirmation.page_status.side_effect = RuntimeError('archive unavailable')
    with pytest.raises(RuntimeError, match='archive unavailable'):
        await c.execute()
    assert c.stats['status'] == 'paused'


async def test_existing_year_position_survives_empty_first_symbol(monkeypatch):
    c = daily_empty_collector(monkeypatch, {CODES[0]})
    c.ingest.state['cursor'] = dict(phase='collecting', codes=CODES, next_index=0,
        next_year=2026, snapshot_hash='previous-snapshot', pages=0, collected=0,
        batch_id='existing-year', fresh=False)
    before = copy.deepcopy(c.ingest.state['cursor'])
    with pytest.raises(CollectionSourceGap):
        await c.execute()
    cursor = c.ingest.state['cursor']
    assert all(cursor[key] == before[key] for key in ('next_index', 'next_year', 'snapshot_hash'))
