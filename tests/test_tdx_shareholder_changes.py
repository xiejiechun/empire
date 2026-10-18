"""Monthly source facts, historical scope and shared asynchronous lifecycle."""
import asyncio
import copy
import json
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.contracts.tdx_performance import SOURCE_COLUMNS, identity, monthly_plan, pack, unpack
from empire.plugins.collectors.tdx_performance import PerformanceCollector
from empire.plugins.collectors.tdx_performance_source import parse, request_body
from tests.prefetch_source import prefetch_http

PERIOD = '2025-08-01'
KIND = 'shareholder_changes'


def source(period=PERIOD, *, revised=False, empty=False, duplicate=False):
    end = int(period[:7].replace('-', '') + '15')
    rows = [[end, end + 1, 10.1234, '股东甲', -1200, 10000, None, None, None, None,
             code, '修订名称' if revised else '来源名称', market, '二级市场买卖']
            for code, market in [('600000', 1), ('000001', 0)]]
    if duplicate:
        rows.append(copy.deepcopy(rows[0]))
    if empty:
        rows = []
    def result(columns, values):
        return dict(ColName=columns, Content=values, Count=len(values))
    return dict(ErrorCode=0, ResultSets=[result(list(SOURCE_COLUMNS[KIND]), rows),
        result(['nflag', 'stype', 'page'], [[0, 'asc', 1]]), result(['count'], [[len(rows)]])])


def setup_collector(monkeypatch):
    c = PerformanceCollector(KIND)
    state = {'revision': 0, 'cursor': {}}
    c.query = SimpleNamespace(state=AsyncMock(return_value={}))
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, json=source())), response_policy=lambda _: None)
    async def publish(events, **kw):
        assert kw['expected_revision'] == state['revision']
        state.update(revision=state['revision'] + 1, cursor=kw['cursor'])
        return dict(state)
    async def advance(**kw):
        state.update(revision=state['revision'] + 1, cursor=kw['cursor'])
        return dict(state)
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(side_effect=lambda _: dict(state)), ensure_capacity=AsyncMock(),
        publish_page=AsyncMock(side_effect=publish), advance_checkpoint=AsyncMock(side_effect=advance), settings={})
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    monkeypatch.setattr('empire.plugins.collectors.tdx_performance.monthly_plan', lambda _: [PERIOD])
    return c, state


def test_source_month_10000_historical_plan_and_duplicate_multiset():
    assert json.loads(request_body(KIND, PERIOD))['Params'] == ['0', 'asc', '202508', '', '1', '1', '10000']
    rows, total = parse(KIND, source(duplicate=True), PERIOD)
    assert total == len(rows) == 3
    assert Counter(r['occurrence'] for r in rows) == {1: 2, 2: 1}
    assert len({identity(KIND, r) for r in rows}) == 3
    assert all(r['announcement_date'] == '2025-08-16' for r in rows)
    assert unpack(KIND, pack(KIND, rows)) == rows
    dates = monthly_plan('2026-10-01')
    assert dates[0] == '1990-01-01' and dates[-1] == '2026-10-01' and len(dates) == 442
    assert parse(KIND, source(empty=True), PERIOD) == ([], 0)


def test_month_precision_start_keeps_exact_precision():
    body = source()
    body['ResultSets'][0]['Content'][0][9] = 201011
    assert next(r for r in parse(KIND, body, PERIOD)[0] if r['unified_code']=='600000.SH')['change_start'] == '2010-11'
    body['ResultSets'][0]['Content'][0][9] = 201013
    with pytest.raises(ValueError):
        parse(KIND, body, PERIOD)


def test_source_unknown_quantity_kept_without_zero_fabrication():
    body = source()
    body['ResultSets'][0]['Content'][0][4] = None
    assert next(r for r in parse(KIND,body,PERIOD)[0] if r['unified_code']=='600000.SH')['shares_changed'] is None


@pytest.mark.parametrize('fault', ['count', 'capacity', 'month', 'field', 'columns', 'page', 'date', 'number'])
def test_incomplete_or_invalid_month_rejected(fault):
    body = source()
    if fault in ('count', 'capacity'):
        body['ResultSets'][2]['Content'][0][0] = 10000 if fault == 'capacity' else 3
    elif fault == 'columns':
        body['ResultSets'][0]['ColName'][0] = 'future'
    elif fault == 'page':
        body['ResultSets'][1]['Content'][0][2] = 2
    else:
        index, value = {'month': (0, 20250901), 'field': (3, None), 'date': (0, 20250230), 'number': (4, True)}[fault]
        body['ResultSets'][0]['Content'][0][index] = value
    with pytest.raises((ValueError, TypeError)):
        parse(KIND, body, PERIOD)


async def test_one_complete_request_final_only_wait_and_complete_history_recheck(monkeypatch):
    c, state = setup_collector(monkeypatch)
    async def confirm(*args):
        assert state['cursor']['phase'] == 'awaiting_archive'
        assert c.ingest.publish_page.await_count % 4 == 0
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    result = await c.execute()
    assert result['collected'] == 2 and c.http.request.await_count == 1
    await c.execute(baseline_revision=state['revision'])
    assert c.http.request.await_count == 2  # Old complete does not suppress repair.
    assert len(json.dumps(result).encode()) < 2048


async def test_source_failure_does_not_publish_or_advance(monkeypatch):
    c, state = setup_collector(monkeypatch)
    body = source()
    body['ResultSets'][2]['Content'] = [[3]]
    c.http.request.return_value = httpx.Response(200, json=body)
    with pytest.raises(ValueError):
        await c.execute()
    assert state['revision'] == 0 and c.ingest.publish_page.await_count == 0


async def test_two_months_publish_without_waiting_prior_archive(monkeypatch):
    c, state = setup_collector(monkeypatch)
    dates = [PERIOD, '2025-09-01']
    monkeypatch.setattr('empire.plugins.collectors.tdx_performance.monthly_plan', lambda _: dates)
    def response(*args, **kw):
        month = json.loads(kw['content'])['Params'][2]
        return httpx.Response(200, json=source(month[:4] + '-' + month[4:] + '-01'))
    c.http.request.side_effect = response
    async def confirm(*args):
        assert c.ingest.publish_page.await_count == 7 and state['cursor']['index'] == 2
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    assert (await c.execute())['collected'] == 4


async def test_partial_market_resume_and_archive_wait_resume(monkeypatch):
    c, state = setup_collector(monkeypatch)
    original = c.ingest.publish_page.side_effect
    async def fail(events, **kw):
        if kw['cursor']['page']==2:
            raise asyncio.CancelledError()
        return await original(events,**kw)
    c.ingest.publish_page.side_effect=fail
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    assert state['cursor']['market_index']==1 and state['cursor']['index']==0
    c.ingest.publish_page.side_effect=original
    c.confirmation.page_status.side_effect=asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await c.execute(baseline_revision=state['revision'])
    requests=c.http.request.await_count
    c.confirmation.page_status.side_effect=None
    assert (await c.execute(baseline_revision=state['revision']))['phase']=='complete'
    assert c.http.request.await_count==requests


async def test_explicit_month_scope_and_message_budget(monkeypatch):
    c,state=setup_collector(monkeypatch)
    c.ingest.settings={'max_page_bytes':100}
    with pytest.raises(ValueError,match='容量'):
        await c.execute(start_month=PERIOD,end_month=PERIOD)
    assert state['revision']==0
    c.ingest.settings={}
    assert (await c.execute(start_month=PERIOD,end_month=PERIOD))['collected']==2
    event=c.ingest.publish_page.call_args.args[0][0]
    assert event.raw_payload['manifest']['start']==PERIOD


async def test_invalid_month_bound_rejected_before_download_or_publish(monkeypatch):
    c,state=setup_collector(monkeypatch)
    with pytest.raises(ValueError,match='月份第一天'):
        await c.execute(end_month='2025-08-15')
    assert c.http.request.await_count==0 and state['revision']==0
