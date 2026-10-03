import pytest

from empire.contracts.security import split_unified_code, unified_code, unit_identity


@pytest.mark.parametrize('market', ['SH', 'SZ', 'BJ'])
def test_round_trip_preserves_market_and_leading_zero(market):
    assert unified_code(market, '000001') == '000001.' + market
    assert split_unified_code('000001.' + market) == (market, '000001')
    assert unit_identity(market + ':000001') == '000001.' + market


@pytest.mark.parametrize('value', ['000001.sz', 'SZ:000001', '1.SZ', '000001.SH.extra',
                                  '０００００１.SZ', None, '000001.HK'])
def test_reject_invalid_unified_code(value):
    with pytest.raises(ValueError):
        split_unified_code(value)


def test_old_beijing_code_remains_distinct_without_alias_evidence():
    assert unified_code('BJ', '830799') != unified_code('BJ', '920799')
    assert unified_code('SH', '000001') != unified_code('SZ', '000001')
