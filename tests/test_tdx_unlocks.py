"""TDX unlock source groups, lifecycle and failures, using minimal observed shapes."""
import asyncio
import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.contracts.unlocks import digest, monthly_plan, pack, unpack, validate_unit
from empire.plugins.collectors.tdx_unlock_source import (
    DETAIL_SOURCE_COLUMNS,
    LIST_COLUMNS,
    detail_params,
    list_params,
    parse_detail,
    parse_list,
)
from empire.plugins.collectors.tdx_unlocks import UnlockCollector
from empire.plugins.datasets.unlocks import list_digest
from tests.prefetch_source import prefetch_http

MONTH = '2020-01-01'


def result(columns, rows):
    return dict(ColName=list(columns), Content=rows, Count=len(rows))


def source(*, revised=False, unknown=False, market=1):
    rows = [[market, '100005', '千禾味业', '603027', '食品', '股权激励',
             None if unknown else 165.23 if revised else 164.23, 20200103, 0, 1000],
            [market, '100005', '千禾味业', '603027', '食品', '股权激励', 8.18, 20200103, 0, 1000]]
    return dict(ErrorCode=0, ResultSets=[result(LIST_COLUMNS, rows), result(['page', 'scode'], [[1, '']]), result(['count'], [[0]])])


def detail(*, empty=False, duplicate=False, revised=False, market=1):
    rows = [] if empty else [['千禾味业', '603027', '来源股东', market, '股权激励', 173.41 if revised else 172.41]]
    if duplicate:
        rows *= 2
    return dict(ErrorCode=0, ResultSets=[result(DETAIL_SOURCE_COLUMNS, rows), result(['scode'], [['603027']])])


def normalized(**kwargs):
    parents = parse_list(source(**kwargs), MONTH)
    children = parse_detail(detail(market=kwargs.get('market', 1)), parents[0])
    return [{**p, 'detail_status': 'present', 'detail_count': len(children)} for p in parents], children


def collector():
    c, state = UnlockCollector(), {'revision': 0, 'cursor': {}}
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.query = SimpleNamespace(state=AsyncMock(return_value={}))
    def response(*args, **kwargs):
        params = json.loads(kwargs['content'])['Params']
        return httpx.Response(200, json=source() if params[0] == '0' else detail())
    c.http = prefetch_http(request=AsyncMock(side_effect=response), response_policy=lambda _: None)
    async def publish(events, **kw):
        assert kw['expected_revision'] == state['revision']
        state.update(revision=state['revision'] + 1, cursor=kw['cursor'])
        return dict(state)
    async def advance(**kw):
        assert kw['expected_revision'] == state['revision']
        state.update(revision=state['revision'] + 1, cursor=kw['cursor'])
        return dict(state)
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(side_effect=lambda _: copy.deepcopy(state)),
        ensure_capacity=AsyncMock(), publish_page=AsyncMock(side_effect=publish),
        advance_checkpoint=AsyncMock(side_effect=advance), settings={})
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    return c, state


async def collect(c, **kw):
    return await c.execute(start_month=MONTH, end_month=MONTH,
        baseline_revision=await c.checkpoint_revision(), **kw)


def test_large_capacity_and_shared_group_preserves_both_facts():
    assert list_params(MONTH) == ['0', '20200101', '20200131', '', '1', '1', '10000000']
    p, d = normalized()
    assert len(p) == 2 and len(d) == 1
    assert len({r['group_key'] for r in p}) == 1 and len({r['record_key'] for r in p}) == 2
    assert {r['shares'] for r in p} == {'1642300', '81800'}
    assert detail_params(p[0]) == ['1', '100005', '20200103', '603027', '1', '1', '10000000']
    validate_unit(MONTH + '|SH', p, d)
    assert unpack(pack(p, d)) == [p, d]
    assert len(monthly_plan('1990-01-01', '2027-12-01')) == 456
    raw = source()
    raw['ResultSets'][2]['Content'] = [[2]]
    assert len(parse_list(raw, MONTH)) == 2
    raw['ResultSets'][2]['Content'] = [[1]]
    assert parse_list(raw, MONTH) == parse_list(source(), MONTH)
    raw['ResultSets'][2]['Content'] = [[3]]
    with pytest.raises(ValueError):
        parse_list(raw, MONTH)


def test_legal_detail_duplicates_and_unchanged_order():
    p = parse_list(source(), MONTH)
    d = parse_detail(detail(duplicate=True), p[0])
    assert sorted(r['occurrence'] for r in d) == [1, 2]
    p = [{**r, 'detail_status': 'present', 'detail_count': 2} for r in p]
    validate_unit(MONTH + '|SH', p, d)
    raw = source()
    raw['ResultSets'][0]['Content'].reverse()
    assert list_digest(parse_list(raw, MONTH)) == list_digest(parse_list(source(), MONTH))
    raw = source()
    raw['ResultSets'][0]['Content'][1][6] = raw['ResultSets'][0]['Content'][0][6]
    raw['ResultSets'][0]['Content'][1][4] = '另一个行业原值'
    expected = parse_list(raw, MONTH)
    raw['ResultSets'][0]['Content'].reverse()
    assert parse_list(raw, MONTH) == expected


@pytest.mark.parametrize('damage', ['count', 'metadata', 'date', 'code', 'precision', 'columns'])
def test_source_failures_are_not_valid_empty(damage):
    raw = source()
    if damage == 'count':
        raw['ResultSets'][0]['Count'] += 1
    elif damage == 'metadata':
        raw['ResultSets'][1]['Content'] = [[2, '']]
    elif damage == 'columns':
        raw['ResultSets'][0]['ColName'][0] = 'future'
    else:
        raw['ResultSets'][0]['Content'][0][{'date': 7, 'code': 3, 'precision': 6}[damage]] = {
            'date': 20200203, 'code': 'bad', 'precision': '0.0000000000001'}[damage]
    with pytest.raises(ValueError):
        parse_list(raw, MONTH)


def test_security_binding_codec_and_same_count_changed_set():
    p, d = normalized()
    raw = detail()
    raw['ResultSets'][0]['Content'][0][1] = '600000'
    with pytest.raises(ValueError):
        parse_detail(raw, p[0])
    with pytest.raises(ValueError):
        unpack({'codec': 'zlib-json-v1', 'bytes': 2, 'body': 'bad!'})
    with pytest.raises(ValueError):
        validate_unit(MONTH + '|SH', p, [])
    changed, _ = normalized(revised=True)
    assert len(changed) == len(p) and list_digest(changed) != list_digest(p)
    from empire.contracts.preparation_scope import PreparationScope
    with pytest.raises(ValueError):
        PreparationScope.parse(dict(start='2200-01-01'))
    assert PreparationScope.parse(dict(start='2200-01-01'), allow_future=True).start == '2200-01-01'


async def test_one_detail_request_shared_by_list_facts_and_final_only_wait():
    c, state = collector()
    async def confirm(*args):
        assert state['cursor']['phase'] == 'awaiting_archive'
        assert c.ingest.publish_page.await_count == 4
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    done = await collect(c)
    assert done['collected'] == 2 and done['details'] == 1 and done['phase'] == 'complete'
    assert c.http.request.await_count == 2


async def test_partial_market_cancel_resume_and_failed_detail_checkpoint():
    c, state = collector()
    original = c.ingest.publish_page.side_effect
    async def fail(events, **kw):
        if kw['cursor']['page'] == 2:
            raise asyncio.CancelledError()
        return await original(events, **kw)
    c.ingest.publish_page.side_effect = fail
    with pytest.raises(asyncio.CancelledError):
        await collect(c)
    assert state['cursor']['market_index'] == 1
    c.ingest.publish_page.side_effect = original
    done = await collect(c)
    assert done['collected'] == 2 and done['page'] == 4
    c, state = collector()
    original = c.http.request.side_effect
    def bad(*a, **kw):
        if json.loads(kw['content'])['Params'][0] == '1':
            raise ValueError('failed detail')
        return original(*a, **kw)
    c.http.request.side_effect = bad
    with pytest.raises(ValueError):
        await collect(c)
    assert state['revision'] == 0


async def test_awaiting_archive_resume_no_download_and_empty_quality():
    c, state = collector()
    c.confirmation.page_status.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await collect(c)
    requests = c.http.request.await_count
    c.confirmation.page_status.side_effect = None
    await collect(c, fresh=True)
    assert c.http.request.await_count == requests
    p = parse_list(source(unknown=True), MONTH)
    assert any(r['shares'] is None for r in p)
    assert parse_detail(detail(empty=True), p[0]) == []


async def test_sql_proofs_skip_unchanged_except_rotating_review(monkeypatch):
    c, state = collector()
    p, d = normalized()
    proof = dict(contract=1, count=2, details=1, empty_groups=0, list_digest=list_digest(p),
                 digest=digest([p, d]), observed_at=datetime.now(UTC).isoformat())
    c.query.state.return_value = dict(contract_version=1, units={MONTH + '|SH': proof})
    # Two months put the one rotating review in the empty next month.
    class Clock:
        @staticmethod
        def now(tz):
            return datetime(2026, 10, 14, tzinfo=tz)
    monkeypatch.setattr('empire.plugins.collectors.tdx_unlocks.datetime', Clock)
    original = c.http.request.side_effect
    def response(*a, **kw):
        params = json.loads(kw['content'])['Params']
        if params[0] == '0' and params[1].startswith('202002'):
            raw = source()
            raw['ResultSets'][0] = result(LIST_COLUMNS, [])
            return httpx.Response(200, json=raw)
        return original(*a, **kw)
    c.http.request.side_effect = response
    await c.execute(start_month=MONTH, end_month='2020-02-01')
    assert c.http.request.await_count == (3 if Clock.now(UTC).date().toordinal() % 2 == 0 else 2)
    assert state['cursor']['collected'] == 2
