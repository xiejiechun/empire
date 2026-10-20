"""Source identity, rolling directory, valuation and ordered queue boundaries."""
import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.unlock_industries.collector import UnlockIndustryCollector
from empire.features.unlock_industries.contract import digest
from empire.features.unlock_industries.source import (
    SOURCE_COLUMNS,
    parse_directory,
    parse_month,
)
from tests.prefetch_source import prefetch_http

BASIS = '2026-10-13'
MONTHS = ['2026-09-01', '2026-10-01']


def result(columns, rows):
    return dict(ColName=columns, Content=rows, Count=len(rows))


def directory(months=None, basis=20261013):
    return dict(ErrorCode=0, ResultSets=[result(['T008'], [[m[:7].replace('-', '')] for m in months or MONTHS]),
                                       result(['mxt'], [[basis]])])


def source(month=MONTHS[0], *, revised=False, empty=False, unknown=False):
    rows = [] if empty else [['航空', None if unknown else 38 if revised else 37.5, 388.125,
                            1180550430271.44, 946651453459.62, 0.00032877, 0.00041],
                           ['船舶', 8031.25, 53770.4375, 652539524759.57, 492271160109.3, 0.08240181, 0.10922931]]
    return dict(ErrorCode=0, ResultSets=[result(SOURCE_COLUMNS.copy(), rows), result(['sstart'], [[month[:7].replace('-', '')]])])


def collector():
    c, state = UnlockIndustryCollector(), {'revision': 0, 'cursor': {}}
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    def response(*args, **kw):
        params = json.loads(kw['content'])['Params']
        return httpx.Response(200, json=directory() if params[0] == 'dxfhy' else source(params[0][:4] + '-' + params[0][4:] + '-01'))
    c.http = prefetch_http(request=AsyncMock(side_effect=response), response_policy=lambda _: None)
    async def publish(events, **kw):
        assert state['revision'] == kw['expected_revision']
        state.update(revision=state['revision'] + 1, cursor=kw['cursor'])
        return copy.deepcopy(state)
    async def advance(**kw):
        return await publish([], **kw)
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(side_effect=lambda _: copy.deepcopy(state)),
        ensure_capacity=AsyncMock(), publish_page=AsyncMock(side_effect=publish), advance_checkpoint=AsyncMock(side_effect=advance))
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    return c, state


async def collect(c, **kw):
    return await c.execute(baseline_revision=await c.checkpoint_revision(), **kw)


def test_source_whole_month_units_basis_and_equal_count_changed_set():
    assert parse_directory(directory()) == (MONTHS, BASIS)
    rows = parse_month(source(), MONTHS[0], BASIS)
    assert rows[0]['shares'] == '375000' and rows[0]['unlock_value'] == '3881250'
    assert rows[0]['market_cap'] == '1180550430271.44' and rows[0]['market_percent'] == '0.00032877'
    assert parse_month(source(empty=True), MONTHS[0], BASIS) == []
    assert parse_month(source(unknown=True), MONTHS[0], BASIS)[0]['shares'] is None
    other = source()
    other['ResultSets'][0]['Content'][1][0] = '煤炭'
    assert digest(parse_month(other, MONTHS[0], BASIS)) != digest(rows)


@pytest.mark.parametrize('damage', ['count', 'echo', 'duplicate', 'precision', 'negative', 'columns'])
def test_protocol_failure_not_empty(damage):
    value = source()
    if damage == 'count':
        value['ResultSets'][0]['Count'] += 1
    elif damage == 'echo':
        value['ResultSets'][1]['Content'] = [['202001']]
    elif damage == 'duplicate':
        value['ResultSets'][0]['Content'][1] = value['ResultSets'][0]['Content'][0]
    elif damage == 'columns':
        value['ResultSets'][0]['ColName'][0] = 'future'
    else:
        value['ResultSets'][0]['Content'][0][2] = '-1' if damage == 'negative' else '0.0000000000001'
    with pytest.raises(ValueError):
        parse_month(value, MONTHS[0], BASIS)
    with pytest.raises(ValueError):
        parse_directory(directory(months=MONTHS * 2))


async def test_one_directory_each_month_once_and_wait_only_after_all_published():
    c, state = collector()
    async def confirm(*args):
        assert c.ingest.publish_page.await_count == 3 and state['cursor']['phase'] == 'awaiting_archive'
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    done = await collect(c)
    assert done['collected'] == 4 and done['phase'] == 'complete' and c.http.request.await_count == 3
    params = [json.loads(call.kwargs['content'])['Params'] for call in c.http.request.call_args_list]
    assert params == [['dxfhy', '0'], ['202609', '20261013'], ['202610', '20261013']]
    assert len(json.dumps(done).encode()) < 8192


async def test_failed_month_no_skip_resume_frozen_directory_final_no_download():
    c, state = collector()
    original = c.ingest.publish_page.side_effect
    async def cancel(events, **kw):
        if kw['cursor']['page'] == 2:
            raise asyncio.CancelledError()
        return await original(events, **kw)
    c.ingest.publish_page.side_effect = cancel
    with pytest.raises(asyncio.CancelledError):
        await collect(c)
    assert state['cursor']['index'] == 1
    c.ingest.publish_page.side_effect = original
    c.confirmation.page_status.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await collect(c)
    assert state['cursor']['phase'] == 'awaiting_archive'
    previous = c.http.request.await_count
    c.confirmation.page_status.side_effect = None
    await collect(c, fresh=True)
    assert c.http.request.await_count == previous
    c, state = collector()
    original = c.http.request.side_effect
    def fail(*a, **kw):
        if json.loads(kw['content'])['Params'][0] == '202609':
            return httpx.Response(200, json=source(empty=True) | {'ErrorCode': -1})
        return original(*a, **kw)
    c.http.request.side_effect = fail
    with pytest.raises(ValueError):
        await collect(c)
    assert state['revision'] == 0
