import asyncio
import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.plugins.collectors.tdx_additional_issues import TdxAdditionalIssuesCollector
from empire.plugins.collectors.tdx_dividends import TdxDividendsCollector
from empire.plugins.collectors.tdx_rights_issues import TdxRightsIssuesCollector
from tests.capital_samples import STOCK, issue_detail, source
from tests.prefetch_source import prefetch_http

CLASSES = (TdxDividendsCollector, TdxAdditionalIssuesCollector, TdxRightsIssuesCollector)


class Publisher:
    def __init__(self):
        self.state = {'revision': 0, 'cursor': {}}
        self.events = []
        self.ensure_capacity = AsyncMock()

    async def checkpoint(self, job):
        return copy.deepcopy(self.state)

    async def publish_page(self, envelopes, *, job_key, expected_revision, cursor, **kw):
        assert expected_revision == self.state['revision']
        self.events.extend(envelopes)
        self.state = dict(revision=expected_revision + 1, cursor=copy.deepcopy(cursor))
        assert len(json.dumps(cursor)) < 4096
        return copy.deepcopy(self.state)

    async def advance_checkpoint(self, *, expected_revision, cursor, **kw):
        self.state = dict(revision=expected_revision + 1, cursor=copy.deepcopy(cursor))


def configured(cls):
    c = cls()
    c.ingest = Publisher()
    c.query = SimpleNamespace(securities=AsyncMock(return_value=[STOCK, dict(market='SH', code='688111', name='第二证券')]))
    c.query.issue_detail_candidates = AsyncMock(return_value=[])
    c.query.verified_issue_candidates = AsyncMock(return_value=[])
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={'status': 'complete'}))
    bodies = []
    async def request(method, url, **kw):
        assert kw['allowed_domains'] == ('tdx.com.cn',) and kw['project_id'] == c.project_id
        params = json.loads(kw['content'])['Params']
        bodies.append(params)
        return httpx.Response(200, json=issue_detail() if url.endswith('tdxsj_xgzx_zfmx') else source(c.kind))
    c.http = prefetch_http(request=AsyncMock(side_effect=request), response_policy=lambda value: value)
    return c, bodies


@pytest.mark.parametrize('cls', CLASSES)
async def test_all_units_enqueued_before_archive_confirmation(cls):
    c, bodies = configured(cls)
    gate = asyncio.Event()
    async def confirm(*args):
        assert c.ingest.events[-1].raw_payload['unit'] == 'manifest'
        await gate.wait()
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    task = asyncio.create_task(c.execute())
    for _ in range(50):
        if c.stats['status'] == 'awaiting_archive':
            break
        await asyncio.sleep(0)
    assert c.stats['status'] == 'awaiting_archive'
    assert len(c.ingest.events) == (3 if c.kind == 'dividends' else 2)
    assert not task.done()
    gate.set()
    result = await task
    assert result['collected'] == (2 if c.kind == 'dividends' else 1)
    if c.kind == 'dividends':
        assert [p[4] for p in bodies] == ['688110', '688111']
    else:
        assert [p[-1] for p in bodies] == (['10000', '1001'] if c.kind == 'additional_issues' else ['10000'])


@pytest.mark.parametrize('cls', CLASSES)
async def test_duplicate_replacing_missing_row_fails_without_checkpoint(cls):
    c, _ = configured(cls)
    c.query.securities.return_value = [STOCK]
    body1 = source(c.kind)
    body1['ResultSets'][0]['Content'] *= 2
    body1['ResultSets'][0]['Count'] = 2
    c.http.request.side_effect = [httpx.Response(200, json=body1)]
    with pytest.raises(ValueError, match='重复'):
        await c.execute()
    assert c.ingest.state['revision'] == 0 and c.ingest.events == []
    assert c.http.request.await_count == 1
    c.records.add_error.assert_awaited_once()
    diagnostic = c.records.add_error.call_args.kwargs
    assert diagnostic['status_code'] == 200 and diagnostic['raw_body']
    assert diagnostic['observed_bytes'] > 0
    if c.kind == 'dividends':
        assert diagnostic['metadata']['security'] == STOCK


async def test_old_dividend_checkpoint_requires_explicit_maintenance():
    c, _ = configured(TdxDividendsCollector)
    c.ingest.state = {'revision': 9, 'cursor': {'phase': 'complete'}}
    with pytest.raises(ValueError, match='显式维护'):
        await c.execute()
    assert not c.http.request.called and c.ingest.state['revision'] == 9


async def test_resume_skips_already_enqueued_units_without_waiting_for_archive():
    c, bodies = configured(TdxDividendsCollector)
    original = c.http.request.side_effect
    async def interrupted(*args, **kw):
        if len(bodies) == 1:
            raise asyncio.CancelledError
        return await original(*args, **kw)
    c.http.request.side_effect = interrupted
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    assert c.ingest.state['cursor']['index'] == 1
    c.confirmation.page_status.assert_not_awaited()
    c.http.request.side_effect = original
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert [p[4] for p in bodies] == ['688110', '688111']
    assert c.ingest.events[-1].raw_payload['manifest']['count'] == 2


@pytest.mark.parametrize('cls', CLASSES)
async def test_resume_archive_wait_does_not_download_and_redis_loss_rechecks(cls):
    c, _ = configured(cls)
    c.confirmation.page_status.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    calls = c.http.request.await_count
    c.confirmation.page_status.side_effect = None
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.http.request.await_count == calls
    c.ingest.state = {'revision': 0, 'cursor': {}}
    await c.execute()
    assert c.http.request.await_count == calls * 2


async def test_pool_change_automatically_starts_a_new_batch_without_skipping():
    c, _ = configured(TdxDividendsCollector)
    original = c.ingest.publish_page
    async def stop_after_first(*args, **kw):
        await original(*args, **kw)
        raise asyncio.CancelledError
    c.ingest.publish_page = stop_after_first
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    c.query.securities.return_value = [STOCK]
    old_batch = c.ingest.state['cursor']['batch_id']
    c.ingest.publish_page = original
    await c.execute(baseline_revision=1)
    assert c.ingest.state['cursor']['units'] == 1
    assert c.ingest.state['cursor']['batch_id'] != old_batch
    assert c.stats['scope_replans'] == 1


@pytest.mark.parametrize('cls', CLASSES)
async def test_valid_empty_response_requires_only_one_read_per_unit(cls):
    c, _ = configured(cls)
    c.query.securities.return_value = [STOCK]
    body = source(c.kind, rows=[], total=1 if c.kind == 'dividends' else 0)
    c.http.request.side_effect = [httpx.Response(200, json=body)]
    assert (await c.execute())['collected'] == 0
    assert c.http.request.await_count == 1
    assert c.ingest.state['cursor']['phase'] == 'complete'


@pytest.mark.parametrize('cls', CLASSES)
async def test_bad_row_count_never_rereads_or_advances(cls):
    c, _ = configured(cls)
    c.query.securities.return_value = [STOCK]
    body = source(c.kind)
    body['ResultSets'][0]['Count'] = 2
    c.http.request.side_effect = [httpx.Response(200, json=body)]
    with pytest.raises(ValueError, match='条数'):
        await c.execute()
    assert c.http.request.await_count == 1 and not c.ingest.events
    assert c.ingest.state['revision'] == 0


@pytest.mark.parametrize('cls', CLASSES)
async def test_transport_failure_uses_shared_retry_budget_without_collector_retry(cls):
    c, _ = configured(cls)
    c.query.securities.return_value = [STOCK]
    c.http.request.side_effect = httpx.ConnectError('shared retries exhausted')
    with pytest.raises(httpx.ConnectError):
        await c.execute()
    assert c.http.request.await_count == 1
    assert c.http.request.call_args.kwargs['max_retries'] == c.request_retries
    assert c.ingest.state['revision'] == 0


@pytest.mark.parametrize('cls', [TdxAdditionalIssuesCollector, TdxRightsIssuesCollector])
async def test_single_read_resume_replans_changed_source_set(cls):
    c, _ = configured(cls)
    original = c.ingest.publish_page
    async def stop_after_first(*args, **kw):
        await original(*args, **kw)
        raise asyncio.CancelledError
    c.ingest.publish_page = stop_after_first
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    before = copy.deepcopy(c.ingest.state)
    c.ingest.publish_page = original
    revised = source(c.kind, amount=7)
    replies = [httpx.Response(200, json=revised)]
    if c.kind == 'additional_issues':
        replies.append(httpx.Response(200, json=issue_detail(revised)))
    c.http.request.side_effect = replies
    await c.execute(baseline_revision=before['revision'])
    assert c.ingest.state['cursor']['batch_id'] != before['cursor']['batch_id']
    assert c.ingest.state['cursor']['phase'] == 'complete'
    assert c.stats['scope_replans'] == 1
    assert c.ingest.events[-1].raw_payload['manifest']['count'] == 1


async def test_changed_source_preserves_forced_detail_refresh_after_interruption():
    c, _ = configured(TdxAdditionalIssuesCollector)
    original = c.ingest.publish_page
    async def stop(*args, **kw):
        await original(*args, **kw)
        raise asyncio.CancelledError
    c.ingest.publish_page = stop
    with pytest.raises(asyncio.CancelledError):
        await c.execute(fresh=True)
    before = copy.deepcopy(c.ingest.state)
    revised = source(c.kind, amount=7)
    c.ingest.publish_page = original
    c.http.request.side_effect = [httpx.Response(200, json=revised),
                                  httpx.Response(200, json=issue_detail(revised))]
    await c.execute(baseline_revision=before['revision'])
    assert c.ingest.state['cursor']['batch_id'] != before['cursor']['batch_id']
    assert c.ingest.state['cursor']['detail_refresh_all'] is True
    c.query.verified_issue_candidates.assert_awaited_once_with([], c.ingest.state['cursor']['detail_refresh_cutoff'])


async def test_changed_source_detail_failure_does_not_commit_new_frontier():
    c, _ = configured(TdxAdditionalIssuesCollector)
    original = c.ingest.publish_page
    async def stop(*args, **kw):
        await original(*args, **kw)
        raise asyncio.CancelledError
    c.ingest.publish_page = stop
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    before = copy.deepcopy(c.ingest.state)
    c.ingest.publish_page = original
    c.http.request.side_effect = [httpx.Response(200, json=source(c.kind, amount=7)),
                                  httpx.Response(200, json={'ErrorCode': -1006})]
    with pytest.raises(ValueError, match='-1006'):
        await c.execute(baseline_revision=before['revision'])
    assert c.ingest.state == before
