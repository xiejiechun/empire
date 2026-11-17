from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from empire.desktop_bridge.schemas import Observation
from empire.features.observation_calendar.query import read
from empire.features.observation_calendar.reading import assemble, bounds


def test_month_grid_and_bounds():
    start, end, _ = bounds('2024-02')
    assert (str(start), str(end)) == ('2024-01-29', '2024-03-03')
    assert len(assemble('2024-02', [], [], [], date(2024, 3, 5))) == 35
    assert bounds('2026-11')[:2] == (date(2026, 10, 26), date(2026, 12, 6))
    assert bounds('1991-01')[2] == date(1990, 12, 19)
    with pytest.raises(ValueError):
        bounds('1990-12')
    for month in ('2024-13', '2024-00', '2100-01'):
        with pytest.raises(ValidationError):
            Observation(month=month, index='000001')


def test_previous_trading_day_missing_quote_unknown_calendar_and_future():
    calendars = [dict(trade_date=f'2026-11-{d:02}', is_trade=state)
                 for d, state in [(2, True), (3, False), (4, True), (5, True), (7, True), (8, True)]]
    prices = [dict(trade_date=f'2026-11-{d:02}', close=close, amount=Decimal('12345678901234.12345678'))
              for d, close in [(2, 100), (4, 110), (7, 120), (8, 130)]]
    margins = [dict(trade_date='2026-11-04', balance_ratio=Decimal('0.0123'), financing_balance=0)]
    days = {r['date']: r for r in assemble('2026-11', calendars, prices, margins, date(2026, 11, 7))}
    assert days['2026-11-04']['values']['change'] == Decimal('10.0')
    assert days['2026-11-04']['values']['balance_ratio'] == Decimal('1.2300')
    assert days['2026-11-04']['values']['financing_balance'] == 0
    assert days['2026-11-04']['values']['amount'] == Decimal('12345678901234.12345678')
    assert days['2026-11-03']['status'] == 'closed'
    assert days['2026-11-06']['status'] == 'unknown'
    assert days['2026-11-07']['values']['change'] is None
    assert days['2026-11-08']['future']
    assert all(v is None for v in days['2026-11-08']['values'].values())


def test_missing_previous_quote_not_bridged_and_zero_denominator():
    calendars = [dict(trade_date=f'2026-11-{d:02}', is_trade=True) for d in range(2, 6)]
    prices = [dict(trade_date=f'2026-11-{d:02}', close=close) for d, close in [(2, 0), (3, 100), (5, 120)]]
    days = {r['date']: r for r in assemble('2026-11', calendars, prices, [], date(2026, 11, 7))}
    assert days['2026-11-03']['values']['change'] is None
    assert days['2026-11-05']['values']['change'] is None


@pytest.mark.asyncio
async def test_adapter_uses_bounded_formal_queries_and_refuses_truncation():
    calendar = SimpleNamespace(month=AsyncMock(return_value={'rows': []}))
    prices = SimpleNamespace(browse=AsyncMock(return_value={'rows': [], 'next': None}))
    margins = SimpleNamespace(browse=AsyncMock(return_value={'rows': [], 'next': None}))
    services = {'calendar.query': calendar, 'index.prices.query': prices, 'market_margin.query': margins}
    registry = SimpleNamespace(get=services.__getitem__)
    result = await read(registry, '2024-02', '000001', '3')
    assert len(result['rows']) == 35
    assert prices.browse.call_args.kwargs == dict(code='000001', start='2023-12-01', end='2024-03-03', limit=200)
    assert margins.browse.call_args.kwargs['search'] == '3'
    prices.browse.return_value['next'] = ['2024-03-03', '000001']
    with pytest.raises(ValueError, match='截断'):
        await read(registry, '2024-02', '000001', '3')
    prices.browse.side_effect = RuntimeError('query failed')
    with pytest.raises(RuntimeError, match='query failed'):
        await read(registry, '2024-02', '000001', '3')


@pytest.mark.asyncio
async def test_bridge_wire_preserves_decimals_and_dispatches_registered_query():
    from empire.desktop_bridge.operations import execute
    service = SimpleNamespace(month=AsyncMock(return_value={'value': Decimal('12345678901234.12345678')}))
    registry = SimpleNamespace(get=lambda capability: service if capability == 'observation.query' else None)
    result = await execute(SimpleNamespace(manager=SimpleNamespace(registry=registry)),
                           'observation.read', {'month': '2026-10', 'index': '1A0001', 'market': '99'})
    assert result['value'] == '12345678901234.12345678'
    service.month.assert_awaited_once_with(month='2026-10', index='1A0001', market='99')


def test_repayment_ratio_is_buy_divided_by_repayment_not_net_buy():
    calendar = [dict(trade_date=f'2026-11-{d:02}', is_trade=True) for d in range(2, 7)]
    margins = [dict(trade_date=f'2026-11-{d:02}', financing_buy=buy, financing_net_buy=net)
               for d, buy, net in [(2, 75, -25), (3, 100, 100), (4, 100, 110), (5, None, 1), (6, 0, -10)]]
    rows = {r['date']: r['values'] for r in assemble('2026-11', calendar, [], margins, date(2026, 11, 6))}
    assert rows['2026-11-02']['financing_repayment_ratio'] == 75
    assert rows['2026-11-02']['financing_ratio_repayment'] == 100
    assert all(rows[f'2026-11-{d:02}']['financing_repayment_ratio'] is None for d in (3, 4, 5))
    assert rows['2026-11-06']['financing_repayment_ratio'] == 0


@pytest.mark.asyncio
async def test_fx_quotes_on_a_share_holiday_missing_future_and_precision():
    from empire.features.observation_calendar.fx import read_fx
    rows = assemble('2026-10', [dict(trade_date='2026-10-01', is_trade=False)], [], [], date(2026, 10, 3))
    query = SimpleNamespace(browse=AsyncMock(return_value=dict(rows=[
        dict(trade_date=date(2026, 10, 1), close=Decimal('7.1234567891'), price_relation_valid=True),
        dict(trade_date=date(2026, 10, 2), close=Decimal('7.13'), price_relation_valid=False),
    ], next=None)))
    registry = SimpleNamespace(get=lambda _: query)
    warnings = await read_fx(registry, '2026-10', rows, ['fx_USDCNH'], {})
    days = {r['date']: r for r in rows}
    assert days['2026-10-01']['status'] == 'closed'
    assert days['2026-10-01']['values']['fx_USDCNH'] == Decimal('7.1234567891')
    assert days['2026-10-02']['values']['fx_USDCNH'] is None
    assert days['2026-10-03']['values']['fx_USDCNH'] is None
    assert days['2026-10-04']['future'] and days['2026-10-04']['values']['fx_USDCNH'] is None
    assert len(warnings) == 1
    assert query.browse.call_args.kwargs == dict(code='USDCNH', start='2026-09-28', end='2026-10-03', limit=500)


@pytest.mark.asyncio
async def test_fx_transforms_use_source_records_and_do_not_skip_invalid_quotes():
    import copy

    from empire.features.observation_calendar.fx import read_fx
    rows = assemble('2026-10', [], [], [], date(2026, 10, 10))
    quotes = [dict(trade_date=f'2026-{stamp}', close=Decimal(value), price_relation_valid=valid)
              for stamp, value, valid in [('09-30', '5', True), ('10-02', '6', True),
                                         ('10-05', '7', False), ('10-06', '8', True)]]
    query = SimpleNamespace(browse=AsyncMock(return_value=dict(rows=list(reversed(quotes)), next=None)))
    registry = SimpleNamespace(get=lambda _: query)
    for mode, expected in [('change', Decimal(20)), ('sum', Decimal('5.5'))]:
        data = copy.deepcopy(rows)
        await read_fx(registry, '2026-10', data, ['fx_USDCNH'], {'fx_USDCNH': dict(mode=mode, days=2)})
        values = {r['date']: r['values']['fx_USDCNH'] for r in data}
        assert values['2026-10-02'] == expected
        assert values['2026-10-01'] is None  # No invented holiday or forward filling.
        assert values['2026-10-05'] is None and values['2026-10-06'] is None
    query.browse.return_value['next'] = ['more']
    with pytest.raises(ValueError, match='截断'):
        await read_fx(registry, '2026-10', rows, ['fx_USDCNH'], {})
    with pytest.raises(ValueError, match='未知或重复'):
        await read_fx(registry, '2026-10', rows, ['fx_USDCNH', 'fx_USDCNH'], {})
    with pytest.raises(ValidationError):
        Observation(month='2026-10', index='1A0001', include_fx=['fx_INVALID'])


@pytest.mark.asyncio
async def test_configured_fx_is_selected_only_and_ratio_basis_follows_own_market(monkeypatch):
    import copy

    from empire.features.observation_calendar import configured
    rows = assemble('2026-10', [dict(trade_date='2026-10-01', is_trade=True)], [], [], date(2026, 10, 2))
    async def base(_registry, month, index, market, **_kwargs):
        data = copy.deepcopy(rows)
        data[3]['values'].update(financing_repayment_ratio=75, financing_ratio_buy=75 if market == '3' else 150,
                                 financing_ratio_repayment=100 if market == '3' else 200)
        return dict(rows=data, month=month, index=index, market=market)
    monkeypatch.setattr(configured, 'read_base', base)
    query = SimpleNamespace(browse=AsyncMock(return_value=dict(rows=[
        dict(trade_date='2026-10-01', close=Decimal('7.1'), price_relation_valid=True)], next=None)))
    registry = SimpleNamespace(get=lambda _: query)
    settings = {'fx_USDCNH': {'mode': 'value'}, 'financing_repayment_ratio': {'market': '3'}}
    result = await configured.configured_read(registry, '2026-10', '1A0001', '99', settings, False, ['fx_USDCNH'])
    values = next(r for r in result['rows'] if r['date'] == '2026-10-01')['values']
    assert values['fx_USDCNH'] == Decimal('7.1')
    assert values['financing_ratio_buy'] == 75 and values['financing_ratio_repayment'] == 100
    query.browse.reset_mock()
    await configured.configured_read(registry, '2026-10', '1A0001', '99', settings, False)
    query.browse.assert_not_awaited()


def test_metric_transform_never_bridges_missing_trading_day():
    from empire.features.observation_calendar.configured import transform
    rows = [dict(date=str(i), status=status, future=False, values={'x': value})
            for i, (status, value) in enumerate([('trade', 10), ('closed', None), ('trade', 20),
                ('trade', None), ('trade', 30), ('unknown', None), ('trade', 40)])]
    assert transform(rows, 'x', {'mode': 'change'}) == {
        '0': None, '1': None, '2': 100, '3': None, '4': None, '5': None, '6': None}
    assert transform(rows, 'x', {'mode': 'sum', 'days': 2})['2'] == 30
    assert transform(rows, 'x', {'mode': 'sum', 'days': 2}, True)['2'] == 15
    assert transform(rows, 'x', {'mode': 'sum', 'days': 2})['4'] is None


def test_top_uses_rolling_security_totals_and_ceiling_rank():
    from empire.features.observation_calendar.concentration import concentration
    days = [dict(date=str(i), status='trade', future=False) for i in range(4)]
    samples = {'0': {'a': Decimal(90), 'b': Decimal(10)},
               '1': {'a': Decimal(10), 'b': Decimal(90)},
               '2': {'a': Decimal(90), 'b': Decimal(10)}, '3': {'a': None}}
    values, counts = concentration(days, samples.get, 2, 50)
    assert values == {'0': None, '1': 50, '2': 50, '3': None}
    assert counts == [2, 2]
    assert concentration(days[:1], samples.get, 1, 1)[0]['0'] == 90


def test_settings_are_strict_and_bounded():
    assert Observation(month='2026-11', index='1A0001', settings={
        'top_amount_share': {'window': 30, 'top': 5}}).settings['top_amount_share'].window == 30
    for option in ({'window': 0}, {'top': 101}, {'days': 61}, {'mode': 'sql'}, {'market': 'all'}):
        with pytest.raises(ValidationError):
            Observation(month='2026-11', index='1A0001', settings={'amount': option})


@pytest.mark.asyncio
async def test_market_turnover_uses_exact_archived_amounts_and_rejects_missing_days():
    from contextlib import nullcontext

    from empire.features.observation_calendar.concentration import read_concentration

    records = [('2026-11-02', 'SH600000', Decimal('12345678901234.12345678')),
               ('2026-11-02', 'SZ000001', Decimal('0.00000001')),
               ('2026-11-02', 'BJ920001', Decimal('2')),
               ('2026-11-03', 'SH600000', Decimal(5)), ('2026-11-03', 'BJ920001', None)]
    class Result:
        closed = False

        def __iter__(self):
            return iter(records)

        def close(self):
            self.closed = True

    result = Result()
    connection = SimpleNamespace(execution_options=lambda **_: SimpleNamespace(execute=lambda *_: result))
    async def read(callback):
        return callback()
    mysql = SimpleNamespace(read=read, read_engine=SimpleNamespace(connect=lambda: nullcontext(connection)))
    registry = SimpleNamespace(get=lambda _: mysql)
    days = [dict(date=f'2026-11-{i:02}', status='trade', future=False) for i in range(2, 5)]
    actual = await read_concentration(registry, days, 1, 5)
    assert actual['turnover'] == {'2026-11-02': Decimal('12345678901236.12345679'),
                                 '2026-11-03': None, '2026-11-04': None}
    assert '不是官方全市场总额' in actual['turnover_warning']
    assert result.closed


@pytest.mark.asyncio
async def test_market_turnover_and_top_share_one_read_and_turnover_transforms_independently(monkeypatch):
    import copy

    from empire.features.observation_calendar import concentration, configured

    rows = assemble('2026-11', [dict(trade_date=f'2026-11-{d:02}', is_trade=True) for d in (2, 3)],
                    [], [], date(2026, 11, 4))
    async def base(_registry, month, index, market, **_kwargs):
        return dict(rows=copy.deepcopy(rows), month=month, index=index, market=market)
    monkeypatch.setattr(configured, 'read_base', base)
    shared = AsyncMock(return_value=dict(values={'2026-11-02': 50, '2026-11-03': 60},
        turnover={'2026-11-02': Decimal(100), '2026-11-03': Decimal(150)}, warning='Top口径', turnover_warning='沪深京样本口径'))
    monkeypatch.setattr(concentration, 'read_concentration', shared)
    actual = await read(None, '2026-11', '1A0001', '3',
        settings={'market_amount': {'mode': 'sum', 'days': 2}}, include_top=True, include_turnover=True)
    shared.assert_awaited_once()
    days = {r['date']: r['values'] for r in actual['rows']}
    assert days['2026-11-02']['market_amount'] is None
    assert days['2026-11-03']['market_amount'] == 250
    assert days['2026-11-03']['top_amount_share'] == 60
    assert actual['warnings'] == ['Top口径', '沪深京样本口径']


@pytest.mark.asyncio
async def test_configured_market_is_independent_and_grid_stays_bounded(monkeypatch):
    import copy

    from empire.features.observation_calendar import configured
    rows = assemble('2026-11', [dict(trade_date='2026-11-02', is_trade=True)], [], [], date(2026, 11, 3))
    async def base(_registry, month, index, market, **_kwargs):
        data = copy.deepcopy(rows)
        for row in data:
            if row['date'] == '2026-11-02':
                row['values']['financing_balance'] = Decimal(10 if market == '3' else 100)
        return dict(rows=data, month=month, index=index, market=market)
    monkeypatch.setattr(configured, 'read_base', base)
    result = await configured.configured_read(None, '2026-11', '1A0001', '99',
        {'financing_balance': {'market': '3', 'mode': 'value'}}, False)
    assert len(result['rows']) == 42
    assert next(r for r in result['rows'] if r['date'] == '2026-11-02')['values']['financing_balance'] == 10
    with pytest.raises(ValueError, match='未知'):
        await configured.configured_read(None, '2026-11', '1A0001', '99', {'unknown': {}}, False)
