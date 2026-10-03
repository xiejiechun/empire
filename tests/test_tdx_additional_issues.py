import copy

import pytest

from empire.plugins.collectors.tdx_capital_source import parse
from empire.plugins.datasets.capital_actions import validate_rows
from tests.capital_samples import source, with_issue_detail


def test_issue_aliases_preserved_and_count_is_source_id():
    body = source('additional_issues')
    alias = copy.deepcopy(body['ResultSets'][0]['Content'][0])
    alias[1], alias[2], alias[10] = '600849', '旧代码', None
    body['ResultSets'][0]['Content'].append(alias)
    body['ResultSets'][0]['Count'] = 2
    rows, total = parse('additional_issues', body, 10000)
    assert total == 1 and len(rows) == 2
    with_issue_detail(rows)
    for r in rows:
        assert r['data']['issued_shares'] == '60000'
        assert 'ClosePrice' not in r['data']
        validate_rows('additional_issues', 'SH:' + r['code'], [r])
    alias[4] = 999
    with pytest.raises(ValueError, match='冲突'):
        parse('additional_issues', body, 10000)


def test_missing_tail_and_same_count_duplicate_rejected():
    with pytest.raises(ValueError, match='总数'):
        parse('additional_issues', source('additional_issues', total=2), 10000)
    body = source('additional_issues')
    body['ResultSets'][0]['Content'] *= 2
    body['ResultSets'][0]['Count'] = 2
    with pytest.raises(ValueError, match='重复'):
        parse('additional_issues', body, 10000)
    with pytest.raises(ValueError, match='截断'):
        parse('additional_issues', source('additional_issues'), 1)


def test_optional_old_issue_dates_stay_unknown():
    body = source('additional_issues')
    for index in (9, 12, 13, 14):
        body['ResultSets'][0]['Content'][0][index] = None
    row = parse('additional_issues', body, 10000)[0][0]
    assert row['event_date'] is None and row['data']['announcement_date'] is None
