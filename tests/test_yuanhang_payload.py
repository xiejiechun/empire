from copy import deepcopy
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from empire.sources.yuanhang_client import HistorySnapshot
from empire.sources.yuanhang_history import (
    CapitalPoint,
    CorporateAction,
    DailyBar,
    FinancialHistory,
)
from empire.sources.yuanhang_payload import (
    daily_years,
    digest,
    financial_payload,
    number,
    validate_financial,
    validate_year,
)

CODE = '605336.SH'


def bar(day, *, code=CODE, amount=None):
    return DailyBar(code, date.fromisoformat(day), *map(Decimal, ('2', '3', '1', '2', '100')), amount)


def snapshot(data):
    return HistorySnapshot('USHT', datetime(2026, 10, 24, tzinfo=UTC), data)


def annual():
    return daily_years(snapshot((bar('2020-10-19'), bar('2022-01-04'))),
                       code=CODE, through=date(2023, 12, 31))


def financial():
    capital = tuple(CapitalPoint(CODE, date(1999, 1, 1), kind, Decimal('100'))
                    for kind in ('circulating', 'free_float', 'total'))
    return financial_payload(snapshot(FinancialHistory((), capital)), code=CODE)


def test_full_daily_split_keeps_empty_middle_and_tail_without_prelisting_coverage():
    units = annual()
    assert [u['year'] for u in units] == [2020, 2021, 2022, 2023]
    assert [u['source_count'] for u in units] == [1, 0, 1, 0]
    assert sum(u['source_count'] for u in units) == 2
    assert units[0]['rows'][0][-1] is None
    assert all(u['native_market'] == 'USHT' for u in units)
    assert units[1]['key_hash'] == digest([])


def test_native_volume_absence_survives_payload_and_old_contract_is_rejected():
    from dataclasses import replace

    unit, = daily_years(snapshot((replace(bar('2020-10-19'), volume_shares=None),)),
                         code=CODE, through=date(2020, 12, 31))
    assert unit['rows'][0][-2:] == [None, None]
    assert validate_year(unit) is unit
    with pytest.raises(ValueError, match='契约'):
        validate_year({**unit, 'contract': 2})


@pytest.mark.parametrize('bars', [(), (bar('2020-10-19'), bar('2020-10-19')),
    (bar('2022-01-04'), bar('2020-10-19')),
    (bar('2020-10-19'), bar('2022-01-04', code='000001.SZ')),
    (bar('2020-10-19'), bar('2027-01-04'))])
def test_bad_complete_response_cannot_publish_even_first_year(bars):
    with pytest.raises(ValueError):
        daily_years(snapshot(bars), code=CODE, through=date(2026, 10, 23))


@pytest.mark.parametrize('value', ['NaN', 'Infinity', '-1', '1000000000000000000',
                                  '0.00000000001', True, 1.2, None])
def test_numeric_contract_rejects_lossy_or_unsupported_values(value):
    with pytest.raises(ValueError):
        number(value)


def test_canonical_decimal_has_no_exponent_and_null_is_not_zero():
    assert number(Decimal('1E+10')) == '10000000000'
    assert number('0.0000000001') == '0.0000000001'
    assert number('-0.00') == '0'
    assert number(None, nullable=True) is None
    assert number('0', nullable=True) == '0'


@pytest.mark.parametrize('change', [
    lambda p: p.update(source_count=2),
    lambda p: p.update(year=2019),
    lambda p: p.update(native_market='USZA'),
    lambda p: p.update(native_market=None),
    lambda p: p.update(contract=True),
    lambda p: p['rows'][0].__setitem__(1, '2.0'),
    lambda p: p['rows'][0].__setitem__(3, '0'),
    lambda p: p.update(rows=[], source_count=0, key_hash=digest([])),
])
def test_annual_payload_rejects_invalid_proof_and_rows(change):
    p = deepcopy(annual()[0])
    change(p)
    with pytest.raises(ValueError):
        validate_year(p)


def test_same_count_different_dates_does_not_match_source_key_proof():
    p = daily_years(snapshot(tuple(bar(d) for d in ('2020-01-02', '2020-01-03', '2020-01-06'))),
                    code=CODE, through=date(2020, 12, 31))[0]
    p['rows'][1][0] = '2020-01-04'
    with pytest.raises(ValueError, match='集合'):
        validate_year(p)


def test_financial_empty_actions_requires_all_capital_kinds_and_keeps_prelisting():
    p = financial()
    assert p['actions'] == [] and p['capital'][0][1] == '1999-01-01'
    p['capital'].pop()
    with pytest.raises(ValueError):
        validate_financial(p)


def test_financial_preserves_future_effective_date_for_as_of_query_filtering():
    action = CorporateAction(CODE, date(2027, 1, 1), *map(Decimal, ('0', '1', '0', '0', '0.5')))
    caps = tuple(CapitalPoint(CODE, date(2027, 1, 1), kind, Decimal('200'))
                 for kind in ('circulating', 'free_float', 'total'))
    p = financial_payload(snapshot(FinancialHistory((action,), caps)), code=CODE)
    assert p['actions'][0] == ['2027-01-01', '0', '1', '0', '0', '0.5']


@pytest.mark.parametrize('change', [
    lambda p: p['capital'].__setitem__(1, p['capital'][0]),
    lambda p: p['capital'].reverse(),
    lambda p: p['capital'][0].__setitem__(2, '0'),
    lambda p: p['capital'][0].__setitem__(1, '2101-01-01'),
    lambda p: p.update(native_market='USZA'),
])
def test_financial_rejects_invalid_sparse_series(change):
    p = financial()
    change(p)
    with pytest.raises(ValueError):
        validate_financial(p)
