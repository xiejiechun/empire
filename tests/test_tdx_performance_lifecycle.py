"""Atomic checkpoints, partial-market resume, bounded prefetch and final-only waiting."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.contracts.tdx_performance import KINDS
from empire.plugins.collectors.tdx_performance import PerformanceCollector
from tests.prefetch_source import prefetch_http
from tests.test_tdx_performance import PERIOD, directory, source


def collector(kind, monkeypatch):
    c = PerformanceCollector(kind)
    state = {'revision': 0, 'cursor': {}}
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.query = SimpleNamespace(state=AsyncMock(return_value={}))
    def response(*args, **kwargs):
        params = json.loads(kwargs['content'])['Params']
        if 'cache' in args[1]:
            return httpx.Response(200, json=directory(kind))
        security = params[1] if kind == 'holder_count' else ''
        return httpx.Response(200, json=source(kind, security=security))
    c.http = prefetch_http(request=AsyncMock(side_effect=response), response_policy=lambda _: None)
    async def publish(events, **kw):
        assert kw['expected_revision'] == state['revision']
        state.update(revision=state['revision'] + 1, cursor=kw['cursor'])
        return dict(state)
    async def advance(**kw):
        assert kw['expected_revision'] == state['revision']
        state.update(revision=state['revision'] + 1, cursor=kw['cursor'])
        return dict(state)
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(side_effect=lambda _: dict(state)),
        ensure_capacity=AsyncMock(), publish_page=AsyncMock(side_effect=publish),
        advance_checkpoint=AsyncMock(side_effect=advance), settings={})
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    monkeypatch.setattr('empire.plugins.collectors.tdx_performance.quarterly_plan', lambda _: [PERIOD])
    return c, state


@pytest.mark.parametrize('kind', KINDS)
async def test_one_request_per_unit_and_final_wait(kind, monkeypatch):
    c, state = collector(kind, monkeypatch)
    async def confirm(*args):
        assert state['cursor']['phase'] == 'awaiting_archive'
        assert c.ingest.publish_page.await_count == (3 if kind == 'holder_count' else 4)
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    result = await c.execute()
    assert c.http.request.await_count == (3 if kind == 'holder_count' else 2)
    assert result['phase'] == 'complete'
    assert result['collected'] == (4 if kind == 'earnings_quick' else 2)
    assert len(json.dumps(result).encode()) < 2048
    assert c.ingest.publish_page.call_args.args[0][0].raw_payload['unit'] == 'manifest'


async def test_partial_market_cancel_resumes_without_double_chain(monkeypatch):
    c, state = collector('earnings_report', monkeypatch)
    original = c.ingest.publish_page.side_effect
    async def fail(events, **kw):
        if kw['cursor']['page'] == 2:
            raise asyncio.CancelledError()
        return await original(events, **kw)
    c.ingest.publish_page.side_effect = fail
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    assert state['cursor']['market_index'] == 1 and state['cursor']['index'] == 0
    first = state['cursor']['rolling']
    c.ingest.publish_page.side_effect = original
    result = await c.execute(baseline_revision=state['revision'])
    assert first and result['collected'] == 2 and result['page'] == 4
    assert [call.args[0][0].raw_payload['unit'] for call in c.ingest.publish_page.call_args_list][-3:] == [PERIOD + '|SZ', PERIOD + '|BJ', 'manifest']


async def test_invalid_source_and_capacity_do_not_publish(monkeypatch):
    c, state = collector('earnings_report', monkeypatch)
    original = c.http.request.side_effect
    def broken(*args, **kw):
        if 'cache' in args[1]:
            return original(*args, **kw)
        body = source(c.kind)
        body['ResultSets'][0]['Content'][1] = body['ResultSets'][0]['Content'][0]
        return httpx.Response(200, json=body)
    c.http.request.side_effect = broken
    with pytest.raises(ValueError):
        await c.execute()
    assert state['revision'] == 0 and c.ingest.publish_page.await_count == 0
    c.http.request.side_effect = original
    c.ingest.settings = {'max_page_bytes': 100}
    with pytest.raises(ValueError, match='容量'):
        await c.execute()
    assert state['revision'] == 0


async def test_awaiting_resume_never_downloads(monkeypatch):
    c, state = collector('earnings_report', monkeypatch)
    c.confirmation.page_status.side_effect = asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    requests = c.http.request.await_count
    c.confirmation.page_status.side_effect = None
    await c.execute(fresh=True, baseline_revision=state['revision'])
    assert c.http.request.await_count == requests
