"""The public reader retains caller-owned snapshots and ordered validation failures."""
from datetime import date
from types import SimpleNamespace

import pytest

from empire.features.adjustment import inputs as adjustment_inputs
from empire.features.kaipanla.query import KaipanlaProductDataPlugin


def test_schema_helper_uses_only_explicit_tables_and_keeps_business_order():
    from empire.features.kaipanla.schema import KEYS, TABLES
    from empire.features.kaipanla.storage_contract import MARKET_TABLES, dataset_tables
    from empire.plugins.infra.schema_manifest import schema_contract

    expected = ('stock_market_day', 'stock_intraday_trend', 'stock_opening_auction',
                'stock_minute_volume', 'stock_intraday_trade_block', 'stock_minute_entrust',
                'stock_large_order_trend', 'stock_daily_quote', 'stock_daily_quote_level')
    assert MARKET_TABLES == expected
    assert tuple(TABLES) == tuple(KEYS) == expected
    assert (TABLES, KEYS) == schema_contract(expected)
    assert schema_contract(()) == ({}, {})
    columns, keys = schema_contract(('stock', 'trade_calendar'))
    assert tuple(columns) == tuple(keys) == ('stock', 'trade_calendar')
    assert keys['stock'] == ['unified_code']
    assert dataset_tables('unrecognized') == dataset_tables('quote')


def test_public_reader_is_lazy_preserves_connection_and_stops_at_first_invalid_day():
    query = object.__new__(KaipanlaProductDataPlugin)
    conn, first, second = object(), object(), object()
    lower, upper = date(2026, 9, 1), date(2026, 9, 2)
    trace = []

    def records(actual_conn, market, code, start, end):
        assert (actual_conn, market, code, start, end) == (conn, 'SZ', '000001', lower, upper)
        trace.append('first batch')
        yield first
        trace.append('second row')
        yield second
        pytest.fail('a failed row must not trigger later batches')

    def decode(stored, market, code):
        assert (market, code) == ('SZ', '000001')
        trace.append('decode first' if stored is first else 'decode second')
        if stored is second:
            raise ValueError('invalid canonical content')
        return first

    query._records, query._decode = records, decode
    values = query.iter_validated_days(conn, 'SZ', '000001', lower, upper)
    assert trace == []
    assert next(values) is first
    assert trace == ['first batch', 'decode first']
    with pytest.raises(ValueError, match='invalid canonical'):
        next(values)
    assert trace == ['first batch', 'decode first', 'second row', 'decode second']


def test_adjustment_uses_only_public_reader_and_same_connection_for_calendar(monkeypatch):
    day, trace = date(2026, 9, 1), []
    row = dict(trade_date=day.isoformat(), lifecycle=dict(listing_date='2021-01-01'),
               data=dict(real=dict(time=150000000, open_px=5, high_px=6, low_px=4, last_px=5.2)))

    def execute(statement, params):
        trace.append('calendar')
        assert params == dict(lower=day, upper=day)
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [dict(trade_date=day, is_trade=1)]))

    conn = SimpleNamespace(execute=execute)

    def read(actual_conn, market, code, lower, upper):
        assert actual_conn is conn
        assert (market, code, lower, upper) == ('SH', '600016', day, day)
        trace.append('quote')
        yield row

    def suspended(actual_conn, security, lower, upper):
        assert actual_conn is conn
        assert (security, lower, upper) == ('600016.SH', day, day)
        trace.append('suspensions')
        return set()

    monkeypatch.setattr(adjustment_inputs, 'suspended', suspended)
    query = SimpleNamespace(iter_validated_days=read)
    assert adjustment_inputs.close_prices(conn, query, 'SH', '600016', day, day)[0]['close'] == '5.2'
    assert trace == ['quote', 'calendar', 'suspensions']
