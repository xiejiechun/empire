import asyncio
import copy
from datetime import date, datetime

import httpx
import pytest

from empire.core.time import CHINA
from empire.plugins.collectors.capital_recovery import recent_plans
from empire.plugins.collectors.tdx_additional_issues import TdxAdditionalIssuesCollector
from empire.plugins.collectors.tdx_capital_source import parse
from empire.plugins.collectors.tdx_dividends import TdxDividendsCollector
from tests.capital_samples import STOCK, issue_detail, source, with_issue_detail
from tests.test_capital_lifecycle import configured


@pytest.mark.parametrize('cls', [TdxDividendsCollector, TdxAdditionalIssuesCollector])
async def test_failed_first_security_does_not_hide_later_data_or_publish_manifest(cls):
    c, _ = configured(cls)
    if c.kind == 'dividends':
        replies = [httpx.Response(200, json={'ErrorCode': -1005}),
                   httpx.Response(200, json=source(c.kind))]
    else:
        body = source(c.kind)
        alias = copy.deepcopy(body['ResultSets'][0]['Content'][0])
        alias[1] = '688111'
        body['ResultSets'][0]['Content'].append(alias)
        body['ResultSets'][0]['Count'] = 2
        alias[15] = 1002  # An independent plan can succeed after the first plan fails.
        body['ResultSets'][2]['Content'] = [[2]]
        alias_body = source(c.kind, code='688111')
        alias_body['ResultSets'][0]['Content'][0][15] = 1002
        replies = [httpx.Response(200, json=body),
                   httpx.Response(200, json={'ErrorCode': -1006}),
                   httpx.Response(200, json=issue_detail(alias_body))]
    c.http.request.side_effect = replies
    with pytest.raises(ValueError):
        await c.execute()
    assert len(c.ingest.events) == 1
    assert c.ingest.events[0].raw_payload['unit'] == 'SH:688111'
    assert c.ingest.state['cursor']['index'] == 0
    assert c.ingest.state['cursor']['collected'] == 0
    assert c.stats['collected'] == 1 and c.stats['queued_records'] == 1
    assert c.stats['continuous_collected'] == 0
    assert c.stats['processed_units'] == 2 and c.stats['failed_units'] == 1
    c.confirmation.page_status.assert_not_awaited()
    # Recovery repairs the frontier and rebuilds an ordered full proof.
    if c.kind == 'dividends':
        c.http.request.side_effect = [httpx.Response(200, json=source(c.kind))] * 2
    else:
        c.http.request.side_effect = [httpx.Response(200, json=body),
                                     httpx.Response(200, json=issue_detail()),
                                     httpx.Response(200, json=issue_detail(alias_body))]
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.ingest.events[-1].raw_payload['manifest']['units'] == 2
    assert c.ingest.state['cursor']['phase'] == 'complete'


def test_recent_plan_window_keeps_unknown_old_and_future_dates_out():
    rows = parse('additional_issues', source('additional_issues'), 10000)[0]
    for value, expected in [('2026-09-30', {'1001'}), ('2026-07-02', {'1001'}),
                            ('2026-07-01', set()), ('2026-10-01', set()), (None, set())]:
        for field in ('issue_date', 'public_issue_date', 'private_issue_date', 'listing_date', 'record_date'):
            rows[0]['data'][field] = value
        assert recent_plans(rows, date(2026, 9, 30)) == expected


async def test_recent_unchanged_details_refresh_once_per_completed_beijing_day():
    c, calls = configured(TdxAdditionalIssuesCollector)
    today = datetime.now(CHINA).date().isoformat()
    body = source(c.kind)
    body['ResultSets'][0]['Content'][0][12:15] = [today] * 3
    rows = parse(c.kind, body, 10000)[0]
    c.query.issue_detail_candidates.return_value = with_issue_detail(rows, body)
    async def request(method, url, **kw):
        calls.append(url)
        return httpx.Response(200, json=issue_detail(body) if url.endswith('tdxsj_xgzx_zfmx') else body)
    c.http.request.side_effect = request
    await c.execute()
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert sum(url.endswith('tdxsj_xgzx_zfmx') for url in calls) == 1


async def test_cancel_and_publish_failure_are_never_skipped():
    c, _ = configured(TdxDividendsCollector)
    async def fail(*args, **kw):
        raise asyncio.CancelledError
    c.ingest.publish_page = fail
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    assert c.http.request.await_count == 1
    assert c.ingest.state['revision'] == 0


async def test_site_wide_outage_stops_after_five_consecutive_units():
    c, _ = configured(TdxDividendsCollector)
    c.query.securities.return_value = [{**STOCK, 'code': f'688{i:03}'} for i in range(20)]
    c.http.request.side_effect = httpx.ConnectError('shared retries exhausted')
    with pytest.raises(httpx.ConnectError):
        await c.execute()
    assert c.http.request.await_count == 5
    assert c.ingest.state['revision'] == 0 and not c.ingest.events


async def test_local_download_configuration_failure_is_not_skipped():
    c, _ = configured(TdxDividendsCollector)
    c.http.request.side_effect = ValueError('响应缓冲预留与请求策略不一致')
    with pytest.raises(ValueError, match='缓冲'):
        await c.execute()
    assert c.http.request.await_count == 1
    assert not c.ingest.events and c.ingest.state['revision'] == 0


async def test_dividend_database_failures_do_not_block_a_valid_sixth_stock():
    c, _ = configured(TdxDividendsCollector)
    c.query.securities.return_value = [{**STOCK, 'code': f'688{i:03}'} for i in range(6)]
    c.http.request.side_effect = [httpx.Response(200, json={'ErrorCode': -1005}) for _ in range(5)] + [
        httpx.Response(200, json=source('dividends'))]
    with pytest.raises(ValueError, match='ErrorCode=-1005'):
        await c.execute()
    assert c.http.request.await_count == 6
    assert len(c.ingest.events) == 1
    assert c.ingest.events[0].raw_payload['unit'] == 'SH:688005'
    assert c.ingest.state['cursor']['index'] == 0
    c.confirmation.page_status.assert_not_awaited()
