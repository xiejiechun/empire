"""Source semantics regressions; these do not claim production coverage."""
import struct
from dataclasses import asdict
from datetime import date
from decimal import Decimal

import pytest

from empire.sources.yuanhang_history import (
    history_query,
    normalize_actions,
    normalize_capital,
    normalize_daily,
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


@pytest.mark.parametrize('changes', [{'8': 3.}, {'9': 5.}, {'7': 0.}, {'13': -1.}, {'19': None}])
def test_invalid_daily_business_values_fail(changes):
    with pytest.raises(ValueError):
        normalize_daily(tables([bar(**changes)]), **BOUNDS)


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
    query = history_query(dataset='capital', instance=1, **BOUNDS)
    assert b'start=0&end=0' in query and b'datatype=1,380,402,407' in query


@pytest.mark.parametrize('code', ['USZA300176', '300176', '300176.SZ&fuquan=Q', '920000.NQ'])
def test_bad_security_is_rejected_before_query(code):
    with pytest.raises(ValueError):
        security_identity(code)
