import copy

import pytest

from empire.plugins.collectors.tdx_capital_source import parse
from empire.plugins.datasets.capital_actions import validate_rows
from tests.capital_samples import source


def test_rights_aliases_and_same_day_different_payment_periods():
    body = source('rights_issues')
    original = body['ResultSets'][0]['Content'][0]
    alias = copy.deepcopy(original)
    alias[12], alias[13], alias[14] = '600849', '旧代码', None
    second = copy.deepcopy(original)
    second[5], second[11] = '2026-01-03', None
    body['ResultSets'][0].update(Content=[original, alias, second], Count=3)
    body['ResultSets'][2]['Content'] = [[2]]
    rows, total = parse('rights_issues', body, 10000)
    assert total == 2 and len(rows) == 3
    for code in ('688110', '600849'):
        group = [r for r in rows if r['code'] == code]
        validate_rows('rights_issues', 'SH:' + code, group)
    assert rows[0]['data']['rights_per_share'] == '0.3'


def test_rights_missing_set_duplicate_and_optional_dates():
    with pytest.raises(ValueError, match='总数'):
        parse('rights_issues', source('rights_issues', total=2), 10000)
    body = source('rights_issues')
    body['ResultSets'][0]['Content'] *= 2
    body['ResultSets'][0]['Count'] = 2
    with pytest.raises(ValueError, match='重复'):
        parse('rights_issues', body, 10000)
    body = source('rights_issues')
    body['ResultSets'][0]['Content'][0][6] = None
    assert parse('rights_issues', body, 10000)[0][0]['data']['payment_end'] is None
