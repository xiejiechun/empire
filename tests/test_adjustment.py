"""Native-source economic counterexamples for theoretical adjustment."""
from copy import deepcopy
from decimal import Decimal

import pytest

from empire.features.adjustment.contract import calculate, ex_reference
from empire.features.capital_actions.event_rules import ActionError


def price(day, value='10'):
    return dict(date=day, **dict.fromkeys(('open', 'high', 'low', 'close'), value))


def action(day='2026-09-02', cash='1', bonus='0', transfer='0', ratio='0', rp='0'):
    return [day, bonus, transfer, ratio, rp, cash]


def approx(value, expected):
    assert abs(Decimal(value)-Decimal(expected)) < Decimal('1e-45')


def test_cash_dividend_keeps_original_and_normalizes_end():
    raw = [price('2026-09-01'), price('2026-09-02', '9')]
    original = deepcopy(raw)
    rows = calculate(raw, [action()])
    assert rows[0]['factor'] == '1' and rows[-1]['forward_multiplier'] == '1'
    approx(rows[0]['forward_close'], '9')
    approx(rows[1]['backward_close'], '10')
    assert rows[1]['close'] == '9' and raw == original
    assert rows[-1]['reference'] == '9'


@pytest.mark.parametrize(('cash', 'shares', 'ratio', 'rp', 'expected'), [
    ('0', '1', '0', '0', '5'), ('0', '0', '0.5', '4', '8'),
    ('1', '0.5', '0.5', '4', '5.5'), ('0', '0', '1', '20', '15'),
])
def test_theoretical_reference(cash, shares, ratio, rp, expected):
    assert ex_reference('10', cash, shares, ratio, rp) == Decimal(expected)


def test_bonus_and_transfer_used_once_with_rights_and_multiple_dates():
    raw = [price('2026-09-01'), price('2026-09-02', '5.5'), price('2026-09-03', '5')]
    events = [action(bonus='0.2', transfer='0.3', ratio='0.5', rp='4'),
              action('2026-09-03', cash='0.5')]
    rows = calculate(raw, events)
    approx(rows[-1]['factor'], '2')
    approx(rows[0]['forward_close'], '5')
    assert rows[1]['events'] == ['2026-09-02']


def test_first_date_is_base_and_future_events_do_not_leak():
    rows = calculate([price('2026-09-01'), price('2026-09-02')],
                     [action('2026-09-01'), action('2026-09-03')])
    assert [r['factor'] for r in rows] == ['1', '1']


@pytest.mark.parametrize('value', [None, True, 'nan', 'inf', '-1', '1e25'])
def test_unknown_or_invalid_numeric_is_not_zero(value):
    with pytest.raises(ActionError):
        calculate([price('2026-09-01'), price('2026-09-02')], [action(cash=value)])


def test_duplicate_event_date_or_missing_event_day_is_rejected():
    raw = [price('2026-09-01'), price('2026-09-03')]
    with pytest.raises(ActionError, match='缺少'):
        calculate(raw, [action()])
    with pytest.raises(ActionError, match='同日'):
        calculate(raw, [action(), action(cash='2')])


def test_rights_requires_price_and_invalid_ohlc_or_cash_over_price_fails():
    raw = [price('2026-09-01'), price('2026-09-02')]
    with pytest.raises(ActionError, match='配股'):
        calculate(raw, [action(ratio='0.4')])
    with pytest.raises(ActionError, match='现金分红'):
        calculate(raw, [action(cash='10')])
    raw[0]['high'] = '9'
    with pytest.raises(ActionError, match='高低价'):
        calculate(raw, [])


def test_full_listing_history_exceeds_old_ten_year_limit_and_repeat_is_stable():
    raw = [price('1991-04-03'), price('2026-09-02')]
    first = calculate(raw, [action()])
    assert first == calculate(raw, [action()])
    assert first != calculate(raw, [action(cash='0.5')])
