"""Economic counterexamples for independently calculated multiplicative factors."""
from copy import deepcopy
from decimal import Decimal

import pytest

from empire.contracts.adjustment import AdjustmentError, calculate, ex_reference


def price(day, value='10'):
    return dict(date=day, **dict.fromkeys(('open', 'high', 'low', 'close'), value))


def dividend(day='2026-09-02', cash='1', shares='0', key='one', status='实施方案'):
    return dict(record_key=key, data=dict(ex_date=day, cash_per_share=cash, total_bonus_per_share=shares,
                                        tax_basis='含税', status=status))


def rights(day='2026-09-02', ratio='0.5', value='4', key='rights'):
    return dict(record_key=key, data=dict(ex_date=day, rights_per_share=ratio, rights_price=value))


def approx(value, expected):
    assert abs(Decimal(value)-Decimal(expected)) < Decimal('1e-45')


def test_cash_dividend_removes_mechanical_drop_and_keeps_raw_price():
    raw = [price('2026-09-01'), price('2026-09-02', '9')]
    original = deepcopy(raw)
    rows = calculate(raw, [dividend()], [])
    assert rows[0]['factor'] == '1' and rows[-1]['forward_multiplier'] == '1'
    approx(rows[0]['forward_close'], '9')
    approx(rows[1]['backward_close'], '10')
    assert rows[1]['close'] == '9' and raw == original
    assert rows[-1]['reference'] == '9'


@pytest.mark.parametrize(('cash', 'shares', 'r', 'rp', 'expected'), [
    ('0', '1', '0', '0', '5'), ('0', '0', '0.5', '4', '8'),
    ('1', '0.5', '0.5', '4', '5.5'), ('0', '0', '1', '20', '15'),
])
def test_theoretical_reference_for_send_transfer_rights_and_combined(cash, shares, r, rp, expected):
    assert ex_reference('10', cash, shares, r, rp) == Decimal(expected)


def test_combined_same_day_and_multiple_events_compound():
    raw = [price('2026-09-01'), price('2026-09-02', '5.5'), price('2026-09-03', '5')]
    rows = calculate(raw, [dividend(cash='1', shares='0.5'), dividend('2026-09-03', cash='0.5', key='two')], [rights()])
    approx(rows[-1]['factor'], '2')
    approx(rows[0]['forward_close'], '5')
    approx(rows[-1]['backward_close'], '10')
    assert rows[1]['events'] == ['one', 'rights']


@pytest.mark.parametrize('status', ['董事会预案', '股东大会预案', '公司预案', '取消分红', '终止'])
def test_non_implemented_plans_never_affect_factors(status):
    raw = [price('2026-09-01'), price('2026-09-02')]
    assert [r['factor'] for r in calculate(raw, [dividend(cash=None, status=status)], [])] == ['1', '1']


def test_first_date_is_relative_base_and_future_events_do_not_leak():
    raw = [price('2026-09-01'), price('2026-09-02')]
    plans = [dividend('2026-09-01', cash=None), dividend('2026-09-03', cash=None, key='future')]
    assert [r['factor'] for r in calculate(raw, plans, [])] == ['1', '1']


@pytest.mark.parametrize('changes', [dict(cash_per_share=None), dict(total_bonus_per_share=None),
    dict(ex_date=None), dict(status='未知'), dict(tax_basis='税后')])
def test_required_components_and_date_are_not_inferred(changes):
    plan = dividend()
    plan['data'].update(changes)
    with pytest.raises(AdjustmentError):
        calculate([price('2026-09-01'), price('2026-09-02')], [plan], [])


def test_send_total_is_authoritative_even_when_source_components_are_null():
    rows = calculate([price('2026-09-01'), price('2026-09-02', '5')], [dividend(cash='0', shares='1')], [])
    assert rows[-1]['factor'] == '2'


@pytest.mark.parametrize('kind', ['dividends', 'rights'])
def test_parallel_same_day_events_are_not_summed_or_selected(kind):
    divs = [dividend(), dividend(cash='2', key='other')] if kind == 'dividends' else []
    rs = [rights(), rights(key='other')] if kind == 'rights' else []
    with pytest.raises(AdjustmentError, match='同日并列'):
        calculate([price('2026-09-01'), price('2026-09-02')], divs, rs)


def test_duplicate_identity_is_error_even_when_counts_match():
    with pytest.raises(AdjustmentError, match='业务键重复'):
        calculate([price('2026-09-01'), price('2026-09-02')], [dividend(), dividend()], [])


def test_event_on_absent_or_suspended_day_is_not_moved_to_later_date():
    with pytest.raises(AdjustmentError, match='2026-09-02'):
        calculate([price('2026-09-01'), price('2026-09-03')], [dividend()], [])


@pytest.mark.parametrize('value', [None, True, 'nan', 'inf', '-1', '1e25'])
def test_invalid_values_rejected(value):
    with pytest.raises(AdjustmentError):
        ex_reference('10', value, '0', '0', '0')


def test_invalid_ohlc_order_and_cash_over_price_rejected():
    raw = [price('2026-09-01'), price('2026-09-02')]
    raw[0]['high'] = '9'
    with pytest.raises(AdjustmentError, match='高低价'):
        calculate(raw, [], [])
    with pytest.raises(AdjustmentError, match='现金分红'):
        calculate([price('2026-09-01'), price('2026-09-02')], [dividend(cash='10')], [])


def test_repeat_and_revision_recompute_and_fixed_anchor():
    raw = [price('2026-09-01'), price('2026-09-02', '9')]
    first = calculate(raw, [dividend()], [])
    assert calculate(raw, [dividend()], []) == first
    assert calculate(raw, [dividend(cash='0.5')], []) != first
    assert calculate(raw[:1], [dividend()], [])[0]['forward_close'] == '10'
