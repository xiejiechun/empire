"""Today's optional quotes remain distinguishable from archived daily facts."""
import asyncio
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.core.time import CHINA
from empire.desktop_bridge.preview import wire
from empire.features.observation_calendar import fx, intraday
from empire.features.observation_calendar.intraday import read_latest, read_live
from empire.features.observation_calendar.reading import assemble

NOW = datetime(2026, 11, 11, 14, 30, tzinfo=CHINA)


def quote(code='USDCNH', **changes):
    return dict(symbol=code, unified_code=code + '.FX', latest='7.1234567891',
        source_time=NOW.isoformat(), source_update_time=NOW.isoformat(),
        observed_at='2026-11-11T06:29:00+00:00', **changes)


def registry(quotes, daily=()):
    latest = SimpleNamespace(browse=AsyncMock(side_effect=lambda code, **_: dict(
        rows=[q for q in quotes if q['symbol'] == code], next=None)))
    archived = SimpleNamespace(browse=AsyncMock(return_value=dict(rows=list(daily), next=None)))
    return SimpleNamespace(get=lambda _: archived, optional=lambda _: latest), latest


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    class Fixed(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)
    monkeypatch.setattr(fx, 'datetime', Fixed)
    monkeypatch.setattr(intraday, 'datetime', Fixed)


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,expected', [('value', '7.1234567891'), ('change', '1.76366841571428571428571428571428571428571428571'), ('sum', '7.06172839455')])
async def test_today_quote_or_estimate_preserves_history_precision_and_metadata(mode, expected):
    rows = assemble('2026-11', [], [], [], NOW.date())
    reg, latest = registry([quote()], [dict(trade_date='2026-11-10', close=Decimal(7), price_relation_valid=True)])
    assert await fx.read_fx(reg, '2026-11', rows, ['fx_USDCNH'], {'fx_USDCNH': dict(mode=mode, days=2)}) == []
    days = {r['date']: r for r in rows}
    assert days['2026-11-11']['values']['fx_USDCNH'] == Decimal(expected)
    assert days['2026-11-10']['values']['fx_USDCNH'] == (Decimal(7) if mode == 'value' else None)
    assert days['2026-11-12']['values']['fx_USDCNH'] is None
    assert 'sources' not in days['2026-11-10']
    source = wire(days['2026-11-11'])['sources']['fx_USDCNH']
    assert source['latest'] == '7.1234567891' and source['source'] == 'redis'
    assert source['mode'] == mode and not source['sampling_stale']
    latest.browse.assert_awaited_once_with(code='USDCNH', limit=12)
    # The same exact computation is available without any archived query.
    reg.get = lambda _: pytest.fail('Incremental refresh must not access SQL services')
    live = await read_live(reg, '2026-11-11', days['2026-11-11']['live_basis'])
    assert live['values']['fx_USDCNH'] == Decimal(expected)
    assert live['sources']['fx_USDCNH'] == days['2026-11-11']['sources']['fx_USDCNH']


@pytest.mark.asyncio
async def test_empty_first_quote_retains_refresh_basis_and_rejects_old_day():
    reg, latest = registry([])
    rows = assemble('2026-11', [], [], [], NOW.date())
    await fx.read_fx(reg, '2026-11', rows, ['fx_USDCNH'], {})
    today = next(r for r in rows if r['date'] == '2026-11-11')
    assert today['live_basis']['fx_USDCNH']['mode'] == 'value'
    latest.browse.side_effect = None
    latest.browse.return_value = dict(rows=[quote()], next=None)
    live = await read_live(reg, today['date'], today['live_basis'])
    assert live['values']['fx_USDCNH'] == Decimal('7.1234567891')
    latest.browse.reset_mock()
    with pytest.raises(ValueError, match='日期已变化'):
        await read_live(reg, '2026-11-10', today['live_basis'])
    latest.browse.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('valid', [True, False])
async def test_same_day_archived_record_even_invalid_is_never_overwritten(valid):
    rows = assemble('2026-11', [], [], [], NOW.date())
    reg, latest = registry([quote()], [dict(trade_date='2026-11-11', close='6.9', price_relation_valid=valid)])
    await fx.read_fx(reg, '2026-11', rows, ['fx_USDCNH'], {})
    today = next(r for r in rows if r['date'] == '2026-11-11')
    assert today['values']['fx_USDCNH'] == (Decimal('6.9') if valid else None)
    assert 'sources' not in today
    latest.browse.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize('field,value', [
    ('observed_at', '2026-11-10T14:29:00+08:00'),
    ('source_time', '2026-11-10T14:29:00+08:00'),
    ('source_update_time', '2026-11-10T23:59:00+08:00'),
    ('source_time', '2026-11-12T00:01:00+08:00'),
    ('source_time', '2026-11-11T14:29:00'),
    ('source_time', '2026-11-11T15:01:00+08:00'),
])
async def test_each_timestamp_must_belong_to_today_and_not_be_naive_or_future(field, value):
    reg, _ = registry([quote() | {field: value}])
    data, warnings = await read_latest(reg, ['fx_USDCNH'], NOW)
    assert not data and len(warnings) == 1


@pytest.mark.asyncio
async def test_stale_sample_is_shown_as_stale_not_silently_refreshed():
    reg, _ = registry([quote() | {'observed_at': '2026-11-11T06:20:00+00:00'}])
    data, warnings = await read_latest(reg, ['fx_USDCNH'], NOW)
    assert not warnings and data['fx_USDCNH']['sampling_stale']
    assert data['fx_USDCNH']['observed_at'] == '2026-11-11T06:20:00+00:00'


@pytest.mark.asyncio
async def test_source_utc_date_is_compared_in_beijing_and_invalid_history_stays_missing():
    reg, _ = registry([quote() | {'source_time': '2026-11-10T23:30:00+00:00'}], [
        dict(trade_date='2026-11-10', close='7', price_relation_valid=False)])
    for mode in ('change', 'sum'):
        rows = assemble('2026-11', [], [], [], NOW.date())
        warnings = await fx.read_fx(reg, '2026-11', rows, ['fx_USDCNH'], {'fx_USDCNH': dict(mode=mode, days=2)})
        today = next(r for r in rows if r['date'] == '2026-11-11')
        assert today['values']['fx_USDCNH'] is None
        assert today['sources']['fx_USDCNH']['source_time'] == '2026-11-10T23:30:00+00:00'
        assert len(warnings) == 1 and 'OHLC' in warnings[0]


@pytest.mark.asyncio
async def test_per_symbol_failure_disabled_provider_empty_and_cancellation():
    reg, latest = registry([quote('EURUSD')])
    good = latest.browse.side_effect
    async def browse(code, **kwargs):
        if code == 'USDCNH':
            raise RuntimeError('password=secret must not escape')
        return good(code=code, **kwargs)
    latest.browse.side_effect = browse
    data, warnings = await read_latest(reg, ['fx_USDCNH', 'fx_EURUSD', 'fx_USDCNY'], NOW)
    assert set(data) == {'fx_EURUSD'} and len(warnings) == 2
    assert 'secret' not in str(warnings)
    assert (await read_latest(SimpleNamespace(optional=lambda _: None), ['fx_USDCNH'], NOW))[1]
    latest.browse.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await read_latest(reg, ['fx_USDCNH'], NOW)


@pytest.mark.asyncio
async def test_timeout_does_not_block_archived_data(monkeypatch):
    reg, latest = registry([])
    class Timeout:
        async def __aenter__(self):
            raise TimeoutError
        async def __aexit__(self, *args):
            return False
    monkeypatch.setattr(asyncio, 'timeout', lambda _: Timeout())
    rows = assemble('2026-11', [], [], [], NOW.date())
    reg.get('').browse.return_value['rows'] = [dict(trade_date='2026-11-10', close='7', price_relation_valid=True)]
    warnings = await fx.read_fx(reg, '2026-11', rows, ['fx_USDCNH'], {})
    assert any('读取失败' in w for w in warnings)
    assert next(r for r in rows if r['date'] == '2026-11-10')['values']['fx_USDCNH'] == 7
    latest.browse.assert_not_awaited()


@pytest.mark.asyncio
async def test_no_today_no_redis_read_and_estimate_does_not_invent_missing_basis():
    reg, latest = registry([quote()])
    rows = assemble('2026-10', [], [], [], NOW.date())
    await fx.read_fx(reg, '2026-10', rows, ['fx_USDCNH'], {})
    latest.browse.assert_not_awaited()
    for mode in ('change', 'sum'):
        rows = assemble('2026-11', [], [], [], NOW.date())
        await fx.read_fx(reg, '2026-11', rows, ['fx_USDCNH'], {'fx_USDCNH': dict(mode=mode, days=2)})
        today = next(r for r in rows if r['date'] == '2026-11-11')
        assert today['values']['fx_USDCNH'] is None
        assert today['sources']['fx_USDCNH']['latest'] == Decimal('7.1234567891')
