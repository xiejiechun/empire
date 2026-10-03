import copy

import pytest

from empire.plugins.collectors.tdx_capital_source import parse
from empire.plugins.datasets.capital_actions import validate_rows
from tests.capital_samples import STOCK, source


def test_detail_is_per_security_not_count_one_plan():
    body = source('dividends')
    second = copy.deepcopy(body['ResultSets'][0]['Content'][0])
    second[0] = '2024-12-31'
    body['ResultSets'][0]['Content'].append(second)
    body['ResultSets'][0]['Count'] = 2
    rows, total = parse('dividends', body, 1, STOCK)
    assert total == 1 and len(rows) == 2
    assert all(r['code'] == '688110' and r['data']['cash_per_share'] == '0.6' for r in rows)
    assert all(r['data']['transfer_per_share'] == '0.49' for r in rows)
    validate_rows('dividends', 'SH:688110', rows)
    other, _ = parse('dividends', body, 1, dict(market='SZ', code='000001', name='另一证券'))
    assert {r['record_key'] for r in other}.isdisjoint(r['record_key'] for r in rows)


def test_empty_detail_and_required_fields():
    assert parse('dividends', source('dividends', rows=[]), 1, STOCK)[0] == []
    bad = source('dividends')
    bad['ResultSets'][0]['Content'][0][3] = 99
    with pytest.raises(ValueError, match='合计'):
        parse('dividends', bad, 1, STOCK)
    bad = source('dividends')
    bad['ResultSets'][0]['Count'] = 99
    with pytest.raises(ValueError, match='条数'):
        parse('dividends', bad, 1, STOCK)


def test_duplicate_replaces_missing_plan_same_count_rejected():
    body = source('dividends')
    body['ResultSets'][0]['Content'] *= 2
    body['ResultSets'][0]['Count'] = 2
    with pytest.raises(ValueError, match='重复'):
        parse('dividends', body, 1, STOCK)


def test_parallel_payouts_same_dates_are_distinct_and_order_independent():
    body = source('dividends', amount=8)
    second = copy.deepcopy(body['ResultSets'][0]['Content'][0])
    second[4] = 5
    body['ResultSets'][0]['Content'].append(second)
    body['ResultSets'][0]['Count'] = 2
    stock = dict(market='SH', code='600007', name='中国国贸')
    rows, _ = parse('dividends', body, 1, stock)
    assert len(rows) == len({r['record_key'] for r in rows}) == 2
    assert {r['data']['cash_per_share'] for r in rows} == {'0.8', '0.5'}
    body['ResultSets'][0]['Content'].reverse()
    assert parse('dividends', body, 1, stock)[0] == rows
    validate_rows('dividends', 'SH:600007', rows)
