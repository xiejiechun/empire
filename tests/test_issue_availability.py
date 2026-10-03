import copy

import httpx
import pytest

from empire.plugins.collectors.tdx_additional_issues import TdxAdditionalIssuesCollector
from empire.plugins.collectors.tdx_capital_source import parse
from empire.plugins.datasets.issue_detail import validate
from tests.capital_samples import issue_detail, source, with_issue_detail
from tests.test_capital_lifecycle import configured


@pytest.mark.parametrize('kind', ['empty', 'source_status'])
async def test_explicit_unavailability_is_admitted_and_completed_without_error(kind):
    c, _ = configured(TdxAdditionalIssuesCollector)
    detail = issue_detail()
    if kind == 'empty':
        detail['ResultSets'][0].update(Count=0, Content=[])
    else:
        detail = {'ErrorCode': -1005, 'ErrorInfo': '数据库执行失败', 'hitCache': False}
    c.http.request.side_effect = [httpx.Response(200, json=source(c.kind)), httpx.Response(200, json=detail)]
    await c.execute()
    row = c.ingest.events[0].raw_payload['rows'][0]
    assert row['data']['detail']['availability'] == 'unavailable'
    assert row['data']['detail']['source_error_code'] == (0 if kind == 'empty' else -1005)
    assert c.ingest.state['cursor']['phase'] == 'complete'
    c.records.add_error.assert_not_awaited()


async def test_unavailable_does_not_discard_last_valid_detail():
    c, _ = configured(TdxAdditionalIssuesCollector)
    prior = with_issue_detail(parse(c.kind, source(c.kind), 10000)[0])
    c.query.issue_detail_candidates.return_value = copy.deepcopy(prior)
    c.http.request.side_effect = [httpx.Response(200, json=source(c.kind)),
                                  httpx.Response(200, json={'ErrorCode': -1005})]
    await c.execute(fresh=True)
    result = c.ingest.events[0].raw_payload['rows'][0]['data']['detail']
    assert result['last_available'] == prior[0]['data']['detail']
    assert validate(result) == result


@pytest.mark.parametrize('detail', [None, {'availability': 'unavailable'},
    {'availability': 'unavailable', 'source_error_code': False},
    {'availability': 'unavailable', 'source_error_code': -999},
    {'availability': 'unavailable', 'source_error_code': -1005, 'last_available': {}}])
def test_unknown_or_malformed_detail_is_not_unavailability(detail):
    with pytest.raises((ValueError, KeyError)):
        validate(detail)
