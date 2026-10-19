import asyncio
import copy

import httpx
import pytest

from empire.features.capital_actions.contract import validate_rows
from empire.features.capital_actions.issue_contract import COLUMNS, parse
from empire.features.capital_actions.issues_collector import TdxAdditionalIssuesCollector
from empire.features.capital_actions.parser import parse as parse_list
from tests.capital_samples import issue_detail, source, with_issue_detail
from tests.test_capital_lifecycle import configured


def test_detail_units_dates_and_first_day_price():
    row = parse_list('additional_issues', source('additional_issues'), 10000)[0][0]
    detail = parse(issue_detail(), row, {'688110'})
    assert detail['gross_proceeds'] == '600000'
    assert detail['online_shares'] == '10000' and detail['offline_shares'] == '20000'
    assert detail['winning_announcement_date'] == '2026-01-03'
    assert detail['first_day_close'] == '12' and detail['post_issue_eps'] == '-0.2'
    assert detail['online_winning_percent'] == '2.5'
    row['data']['detail'] = detail
    validate_rows('additional_issues', 'SH:688110', [row])
    del row['data']['detail']
    with pytest.raises(ValueError, match='未补齐'):
        validate_rows('additional_issues', 'SH:688110', [row])


@pytest.mark.parametrize('mutation', ['duplicate', 'code', 'amount', 'date', 'missing', 'infinite'])
async def test_bad_detail_retains_checkpoint_and_real_diagnostic(mutation):
    c, _ = configured(TdxAdditionalIssuesCollector)
    body = issue_detail()
    table = body['ResultSets'][0]
    if mutation == 'empty':
        table.update(Count=0, Content=[])
    elif mutation == 'duplicate':
        table.update(Count=2, Content=table['Content'] * 2)
    elif mutation == 'missing':
        table['ColName'] = table['ColName'][:-1]
    else:
        field, value = {'code': ('code', '000001'), 'amount': ('T005', 999),
                        'date': ('T102', '2026-01-02 12:30:00'),
                        'infinite': ('T026', 'Infinity')}[mutation]
        table['Content'][0][COLUMNS.index(field)] = value
    c.http.request.side_effect = [httpx.Response(200, json=source('additional_issues')),
                                  httpx.Response(200, json=body)]
    with pytest.raises(ValueError):
        await c.execute()
    assert c.ingest.state['revision'] == 0 and not c.ingest.events
    assert c.http.request.await_count == 2
    c.records.add_error.assert_awaited_once()
    fields = c.records.add_error.call_args.kwargs
    assert fields['metadata']['source_id'] == '1001'
    assert fields['raw_body'] and fields['request_url'].endswith('tdxsj_xgzx_zfmx')


async def test_alias_details_requested_once_and_resume_skips_published_security():
    c, calls = configured(TdxAdditionalIssuesCollector)
    body = source('additional_issues')
    alias = copy.deepcopy(body['ResultSets'][0]['Content'][0])
    alias[1] = '688111'
    body['ResultSets'][0]['Content'].append(alias)
    body['ResultSets'][0]['Count'] = 2
    c.http.request.side_effect = [httpx.Response(200, json=body), httpx.Response(200, json=issue_detail())]
    await c.execute()
    assert c.http.request.await_count == 2
    assert c.ingest.events[-1].raw_payload['manifest']['count'] == 2
    c, calls = configured(TdxAdditionalIssuesCollector)
    original = c.ingest.publish_page
    async def stop(*args, **kw):
        await original(*args, **kw)
        raise asyncio.CancelledError
    c.ingest.publish_page = stop
    c.http.request.side_effect = [httpx.Response(200, json=body), httpx.Response(200, json=issue_detail())]
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    assert c.ingest.state['cursor']['index'] == 1
    c.confirmation.page_status.assert_not_awaited()
    c.ingest.publish_page = original
    c.http.request.side_effect = [httpx.Response(200, json=body), httpx.Response(200, json=issue_detail())]
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert len(c.ingest.events) == 3
    assert c.ingest.events[1].raw_payload['unit'] == 'SH:688111'


async def test_old_issue_checkpoint_rejected_even_if_complete():
    c, _ = configured(TdxAdditionalIssuesCollector)
    c.ingest.state = dict(revision=4, cursor=dict(schema_version=1, phase='complete'))
    with pytest.raises(ValueError, match='显式维护'):
        await c.execute()
    assert c.http.request.await_count == 0


def test_unknown_optional_detail_values_remain_null():
    row = parse_list('additional_issues', source('additional_issues'), 10000)[0][0]
    body = issue_detail()
    for field in ('T102', 'T109', 'T026', 'cT012'):
        body['ResultSets'][0]['Content'][0][COLUMNS.index(field)] = '' if field == 'T102' else None
    detail = parse(body, row, {'688110'})
    assert all(detail[k] is None for k in ('winning_announcement_date', 'issue_targets', 'gross_proceeds', 'lead_underwriter'))


@pytest.mark.parametrize('condition', ['unchanged', 'missing', 'corrupt', 'changed', 'new', 'null'])
async def test_incremental_details_request_only_when_needed(condition):
    c, calls = configured(TdxAdditionalIssuesCollector)
    archived = with_issue_detail(parse_list('additional_issues', source('additional_issues'), 10000)[0])
    if condition == 'missing':
        del archived[0]['data']['detail']
    elif condition == 'corrupt':
        archived[0]['data']['detail']['gross_proceeds'] = 'broken'
    elif condition == 'changed':
        archived[0]['data']['issue_price'] = '9'
    elif condition == 'new':
        archived = []
    elif condition == 'null':
        archived[0]['data']['detail'] = {k: None for k in archived[0]['data']['detail']}
    c.query.issue_detail_candidates.return_value = archived
    await c.execute()
    assert len(calls) == (1 if condition in ('unchanged', 'null') else 2)
    c.query.issue_detail_candidates.assert_awaited_once()
    assert 'detail' in c.ingest.events[0].raw_payload['rows'][0]['data']


async def test_incremental_new_alias_reuses_plan_and_conflicting_aliases_refetch():
    from empire.features.capital_actions.issue_source import reusable_details
    base = parse_list('additional_issues', source('additional_issues'), 10000)[0]
    archived = with_issue_detail(copy.deepcopy(base))
    alias = copy.deepcopy(archived[0])
    alias['code'] = '688111'
    from empire.features.capital_actions.contract import digest
    alias['record_key'] = digest(['SH', '688111', '1001'])
    assert reusable_details([alias], base)['1001'] == archived[0]['data']['detail']
    alias['data']['detail']['issue_targets'] = '不同详情'
    assert reusable_details([alias, archived[0]], base) == {}


async def test_explicit_full_refresh_survives_interruption_without_sql_reuse():
    c, calls = configured(TdxAdditionalIssuesCollector)
    c.query.issue_detail_candidates.return_value = with_issue_detail(
        parse_list('additional_issues', source('additional_issues'), 10000)[0])
    original = c.ingest.publish_page
    async def stop(*args, **kw):
        await original(*args, **kw)
        raise asyncio.CancelledError
    c.ingest.publish_page = stop
    with pytest.raises(asyncio.CancelledError):
        await c.execute(fresh=True)
    assert c.ingest.state['cursor']['detail_refresh_all'] is True
    assert len(calls) == 2
    c.query.issue_detail_candidates.assert_awaited_once()
    c.ingest.publish_page = original
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.query.issue_detail_candidates.await_count == 2
    assert c.ingest.state['cursor']['phase'] == 'complete'


async def test_redis_cursor_loss_reuses_archived_details():
    c, calls = configured(TdxAdditionalIssuesCollector)
    c.query.issue_detail_candidates.return_value = with_issue_detail(
        parse_list('additional_issues', source('additional_issues'), 10000)[0])
    await c.execute()
    c.ingest.state = dict(revision=0, cursor={})
    await c.execute()
    assert calls == [['0', '', '1', '1', '10000']] * 2


async def test_source_unavailable_is_requested_once_for_all_code_aliases():
    c, _ = configured(TdxAdditionalIssuesCollector)
    body = source(c.kind)
    alias = copy.deepcopy(body['ResultSets'][0]['Content'][0])
    alias[1] = '688111'
    body['ResultSets'][0]['Content'].append(alias)
    body['ResultSets'][0]['Count'] = 2
    c.http.request.side_effect = [httpx.Response(200, json=body),
                                 httpx.Response(200, json={'ErrorCode': -1005})]
    await c.execute()
    assert c.http.request.await_count == 2
    assert c.stats['details_requested'] == 1 and c.stats['details_unavailable'] == 2
    c.records.add_error.assert_not_awaited()
    assert c.ingest.state['cursor']['phase'] == 'complete'
    assert c.ingest.events[0].raw_payload['rows'][0]['data']['detail']['availability'] == 'unavailable'


async def test_five_business_failures_do_not_block_a_valid_sixth_security():
    c, _ = configured(TdxAdditionalIssuesCollector)
    body = source(c.kind)
    raw = body['ResultSets'][0]['Content'][0]
    values = []
    for i in range(6):
        row = copy.deepcopy(raw)
        row[1], row[15] = f'688{i + 110}', 1001 + i
        values.append(row)
    body['ResultSets'][0].update(Content=values, Count=6)
    body['ResultSets'][2]['Content'] = [[6]]
    last = source(c.kind, code='688115')
    last['ResultSets'][0]['Content'][0][15] = 1006
    c.http.request.side_effect = [httpx.Response(200, json=body)] + [
        httpx.Response(200, json={'ErrorCode': -1005}) for _ in range(5)] + [
        httpx.Response(200, json=issue_detail(last))]
    await c.execute()
    assert c.http.request.await_count == 7
    assert len(c.ingest.events) == 7
    assert c.ingest.events[-2].raw_payload['unit'] == 'SH:688115'
    assert c.stats['details_unavailable'] == 5
    assert c.ingest.state['cursor']['phase'] == 'complete'
