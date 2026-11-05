"""Source semantics regressions; these do not claim production coverage."""
import struct
from dataclasses import asdict
from datetime import date
from decimal import Decimal

import pytest

from empire.sources.yuanhang_history import (
    IncompleteFinancialHistory,
    MissingFinancialValue,
    history_query,
    normalize_actions,
    normalize_capital,
    normalize_daily,
    normalize_financial,
    price_quality,
    security_identity,
)
from empire.sources.yuanhang_wire import decode_response

BOUNDS = dict(unified_code='300176.SZ', start=date(1990, 1, 1), end=date(2026, 10, 23))


def tables(rows, security='USZA300176'):
    return [dict(fields=[(f, 4 if f == 1 else 3, 0, 4 if f == 1 else 8) for f in rows[0]],
                 rows=rows, extra={5: security})]


def bar(day=20261023, **changes):
    row = {1: day, 7: Decimal('4.00'), 8: Decimal('4.17'), 9: Decimal('3.85'),
           11: Decimal('4.15'), 13: Decimal('14836966'), 19: Decimal('59154445')}
    row.update({int(k): v for k, v in changes.items()})
    return row


def action(day=20180529, **changes):
    row = {1: day, 454: 0.9, 455: 0., 456: 0., 460: 0.9, 463: 1.1}
    row.update({int(k): v for k, v in changes.items()})
    return row


def test_daily_wire_to_typed_values_and_units():
    # Real observed 300176 values in a minimal binary table, not a saved response.
    values = {1: 20261023, 7: 4., 8: 4.17, 9: 3.85, 11: 4.15, 13: 14836966., 19: 59154445.}
    descriptors = b''.join(struct.pack('<IBBH', f, 4 if f == 1 else 3, 0, 4 if f == 1 else 8)
                           for f in values)
    data = struct.pack('<i', values[1]) + b''.join(struct.pack('<d', v) for f, v in values.items() if f != 1)
    extra = struct.pack('<IBBH', 5, 1, 0, 11) + b'USZA300176\0'
    table = b'hx1.0\0' + struct.pack('<iIHHI', 1, 22 + len(descriptors), len(data), 7, len(extra))
    table += descriptors + data + extra
    payload = struct.pack('<I', len(table)) + table
    response = struct.pack('<HiIHiB', 17, 1, 210, 1, len(payload), 1) + payload
    result, = normalize_daily(decode_response(response, instance=1, request_id=210), **BOUNDS)
    assert result.trade_date == date(2026, 10, 23)
    assert result.close == Decimal('4.15')
    assert result.volume_shares == Decimal('14836966')  # Not lots of 100 shares.
    assert result.amount_yuan == Decimal('59154445')
    assert all(type(v) is Decimal for k, v in asdict(result).items() if k not in ('unified_code', 'trade_date'))


def test_transfer_is_not_double_counted_and_rights_units_are_per_share():
    transfer, rights = normalize_actions(tables([
        action(), action(20260821, **{'454': 0., '460': 0., '463': 0., '455': .4, '456': 3.36}),
    ]), **BOUNDS)
    assert (transfer.bonus_ratio, transfer.transfer_ratio, transfer.cash_per_share) == (0, Decimal('.9'), Decimal('1.1'))
    assert (rights.rights_ratio, rights.rights_price) == (Decimal('.4'), Decimal('3.36'))
    bonus, = normalize_actions(tables([action(20030714, **{'454': .1, '460': 0., '463': .2})]), **BOUNDS)
    assert (bonus.bonus_ratio, bonus.transfer_ratio) == (Decimal('.1'), 0)


def test_sparse_capital_does_not_join_by_position_or_backfill_dates():
    source = tables([{1: 20260821, 380: 290082764.}, {1: 20260902, 380: 395376669.}])
    source += tables([{1: 20260820, 402: 600000000., 407: 500000000.}])
    records = normalize_capital(source, **BOUNDS)
    assert [(r.kind, r.effective_date, r.shares) for r in records] == [
        ('circulating', date(2026, 8, 20), Decimal('500000000')),
        ('free_float', date(2026, 8, 21), Decimal('290082764')),
        ('free_float', date(2026, 9, 2), Decimal('395376669')),
        ('total', date(2026, 8, 20), Decimal('600000000')),
    ]


def test_equal_counts_with_different_date_sets_fail():
    source = tables([{1: 20261022, 7: 4., 8: 5., 9: 3.}])
    source += tables([{1: 20261023, 11: 4., 13: 100., 19: 400.}])
    with pytest.raises(ValueError, match='date sets'):
        normalize_daily(source, **BOUNDS)


@pytest.mark.parametrize('value', [None, True, '4.15', float('nan'), float('inf'), -1, Decimal('1e18'), Decimal('4.12345678901')])
def test_missing_invalid_or_excess_precision_never_rounds_or_becomes_zero(value):
    with pytest.raises(ValueError):
        normalize_daily(tables([bar(**{'11': value})]), **BOUNDS)


@pytest.mark.parametrize('changes', [{'8': 0.}, {'9': 0.}, {'7': 0.}, {'13': -1.}, {'19': -1.}])
def test_invalid_daily_business_values_fail(changes):
    with pytest.raises(ValueError):
        normalize_daily(tables([bar(**changes)]), **BOUNDS)


def test_000529_source_inconsistent_high_is_retained_with_derived_quality():
    result, = normalize_daily(tables([bar(20001016, **{'7': 7.65, '8': 7.82, '9': 7.65, '11': 7.83})]), **BOUNDS)
    assert (result.high, result.close) == (Decimal('7.82'), Decimal('7.83'))
    assert price_quality(result.open, result.high, result.low, result.close) == 1


@pytest.mark.parametrize('changes', [{'460': 1.}, {'455': .4, '456': 0.}, {'463': None}, {'454': -.1}])
def test_invalid_actions_fail(changes):
    with pytest.raises(ValueError):
        normalize_actions(tables([action(**changes)]), **BOUNDS)


def test_source_unsupported_marker_is_not_stripped_to_create_actual_float():
    with pytest.raises(ValueError, match='omitted'):
        normalize_capital(tables([{1: 20261023, 0x80000000 | 380: None}]), fields=frozenset({380}), **BOUNDS)
    with pytest.raises(ValueError, match='unverified'):
        normalize_capital(tables([{1: 20261023, 2988: 1.}]), fields=frozenset({2988}), **BOUNDS)


def test_queries_use_verified_markets_and_no_adjustment_parameter():
    assert security_identity('920000.BJ') == 'USTM920000'
    query = history_query(unified_code='920000.BJ', dataset='daily', start=date(1990, 1, 1),
                          end=date(2026, 10, 23), instance=5)
    assert b'market=USTM&code=920000&start=19900101&end=20261023' in query
    assert b'fuquan' not in query and b'instance=5' in query
    query = history_query(dataset='financial', instance=1, **BOUNDS)
    assert b'start=0&end=0' in query and b'datatype=1,380,402,407,454,455,456,460,463' in query


def test_source_missing_amount_keeps_day_and_is_not_zero():
    row, = normalize_daily(tables([bar(20050105, **{'19': None})]), **BOUNDS)
    assert row.trade_date == date(2005, 1, 5)
    assert row.amount_yuan is None
    assert row.volume_shares == Decimal('14836966')


def test_002042_explicit_missing_volume_keeps_bar_without_fabricating_no_trade():
    row, = normalize_daily(tables([bar(20061206, **{'7': 3.33, '8': 3.33, '9': 3.33,
                                                   '11': 3.33, '13': None, '19': None})]), **BOUNDS)
    assert row.trade_date == date(2006, 12, 6)
    assert row.volume_shares is row.amount_yuan is None
    assert row.close == Decimal('3.33')
    broken = bar()
    del broken[13]
    with pytest.raises(ValueError, match='omitted'):
        normalize_daily(tables([broken]), **BOUNDS)


def capital_tables():
    return (tables([{1: 20110215, 402: 89400000., 407: 18000000.}])
            + tables([{1: 20110215, 380: 18000000.}]))


@pytest.mark.parametrize('field', [380, 402, 454, 455, 456, 460, 463])
def test_explicit_financial_null_has_precise_identity_and_date(field):
    source = capital_tables() + tables([action()])
    for table in source:
        for row in table['rows']:
            if field in row:
                row[field] = None
    with pytest.raises(MissingFinancialValue) as caught:
        normalize_financial(source, **BOUNDS)
    assert caught.value.field == field and caught.value.code == BOUNDS['unified_code']
    assert caught.value.day == (20110215 if field in (380, 402) else 20180529)


@pytest.mark.parametrize('value', [True, '1', -1, float('nan'), float('inf')])
def test_invalid_financial_value_is_not_classified_as_confirmable_null(value):
    source = capital_tables()
    source[0]['rows'][0][402] = value
    with pytest.raises(ValueError) as caught:
        normalize_financial(source, **BOUNDS)
    assert not isinstance(caught.value, MissingFinancialValue)


def test_financial_empty_actions_requires_all_capital_series_and_identity():
    result = normalize_financial(capital_tables(), **BOUNDS)
    assert result.actions == () and len(result.capital) == 3
    with pytest.raises(ValueError, match='omitted'):
        normalize_financial(capital_tables()[:1], **BOUNDS)
    with pytest.raises(ValueError, match='identity'):
        normalize_financial(tables([{1: 20110215, 402: 1., 407: 1., 380: 1.}], 'USZA999999'), **BOUNDS)
    with pytest.raises(ValueError):
        normalize_financial([], **BOUNDS)


@pytest.mark.parametrize('mode', ['valid', 'wrong_security', 'bad_date', 'future', 'null', 'null_total', 'zero',
                                  'unknown', 'unsupported', 'partial_action', 'two_points', 'missing_total'])
def test_only_verified_single_partial_capital_point_has_distinct_unavailability(mode):
    row = {1: 20250627, 402: 100000000., 407: 10000000.}
    security = 'USZA300176'
    if mode == 'wrong_security':
        security = 'USZA999999'
    if mode == 'bad_date':
        row[1] = 20250230
    if mode == 'future':
        row[1] = 20271023
    if mode in ('null', 'zero'):
        row[407] = None if mode == 'null' else 0
    if mode == 'null_total':
        row[402] = None
    if mode in ('unknown', 'unsupported', 'partial_action'):
        row[{'unknown': 471, 'unsupported': 0x80000000 | 380, 'partial_action': 454}[mode]] = 0.
    if mode == 'missing_total':
        del row[402]
    rows = [row] if mode != 'two_points' else [row, {**row, 1: 20250628}]
    with pytest.raises(ValueError) as caught:
        normalize_financial(tables(rows, security), **BOUNDS)
    assert isinstance(caught.value, IncompleteFinancialHistory) == (mode in ('valid', 'null'))


def test_combined_financial_keeps_separate_dates_and_transfer_semantics():
    result = normalize_financial(capital_tables() + tables([action()]), **BOUNDS)
    assert result.actions[0].transfer_ratio == Decimal('.9')
    assert result.actions[0].bonus_ratio == 0
    assert result.actions[0].ex_date == date(2018, 5, 29)
    assert {p.effective_date for p in result.capital} == {date(2011, 2, 15)}


@pytest.mark.parametrize('extra', [
    [{1: 20180529, 454: 0.}],
    [{1: 20180529, 0x80000000 | 454: None}],
    [{1: 20180529, 471: 'unrequested'}],
    [action(**{'463': None})],
])
def test_partial_unsupported_unknown_or_null_actions_never_mean_empty(extra):
    with pytest.raises(ValueError):
        normalize_financial(capital_tables() + tables(extra), **BOUNDS)


@pytest.mark.parametrize('code', ['USZA300176', '300176', '300176.SZ&fuquan=Q', '920000.NQ'])
def test_bad_security_is_rejected_before_query(code):
    with pytest.raises(ValueError):
        security_identity(code)


def test_risk_board_keeps_sh_business_identity_and_checks_native_identity():
    bounds = {**BOUNDS, 'unified_code': '605336.SH', 'native_market': 'USHT'}
    row, = normalize_daily(tables([bar()], 'USHT605336'), **bounds)
    assert row.unified_code == '605336.SH'
    query = history_query(dataset='daily', instance=1, **bounds)
    assert b'market=USHT&code=605336' in query
    with pytest.raises(ValueError, match='identity'):
        normalize_daily(tables([bar()], 'USHA605336'), **bounds)
    for code, market in [('605336.SH', 'USZA'), ('300176.SZ', 'USHT'), ('920000.BJ', 'USHA')]:
        with pytest.raises(ValueError, match='native market'):
            security_identity(code, market)
