from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.repurchases import dataset
from empire.features.repurchases.contract import digest, normalize
from empire.features.repurchases.incremental import refresh_plan
from tests.test_repurchases import collector, feed, source_row


def test_refresh_plan_requires_recent_full_anchor_and_rejects_future_or_broken_proof():
    now = datetime(2026, 11, 5, tzinfo=UTC)
    proof = dict(contract=1, count=1, digest='a'*64, observed_at=(now-timedelta(days=1)).isoformat())
    assert refresh_plan(proof, now)['since'] == '2026-11-01'
    assert refresh_plan(dict(proof, full_observed_at=(now-timedelta(days=3)).isoformat()), now) is None
    assert refresh_plan(dict(proof, observed_at=(now+timedelta(seconds=1)).isoformat()), now) is None
    assert refresh_plan(dict(proof, digest='x'*64), now) is None


@pytest.mark.parametrize('empty', [False, True])
async def test_incremental_filters_and_publishes_composed_proof_only_after_data_drains(empty):
    item = collector([])
    scope = dict(since='2026-11-01', full_observed_at='2026-11-03T00:00:00.000000+00:00', proof=False)
    item.query.refresh_plan.return_value = scope
    row = source_row('2', UPD='2026-11-04 00:00:00')
    async def request(*args, **kwargs):
        assert kwargs['params']['filter'] == "(UPD>='2026-11-01')"
        body = dict(success=False, result=None, message='返回数据为空') if empty else feed([row])
        return httpx.Response(200, request=httpx.Request('GET', args[1]), json=body)
    item.http.request.side_effect = request
    async def summary():
        assert item.confirmation.page_status.await_count == 1
        return dict(count=8, digest='f'*64, invalid=0)
    item.query.current_summary = AsyncMock(side_effect=summary)
    result = await item.execute()
    assert result['coverage_count'] == 8 and result['coverage_digest'] == 'f'*64
    assert item.confirmation.page_status.await_count == 2
    events = item.ingest.events
    first = dataset.normalize(events[0])
    last = dataset.normalize(events[-1])
    assert dataset.COVERAGE_KEY not in dataset.fingerprint_plan(events[0], first)[1]
    assert dataset.COVERAGE_KEY in dataset.fingerprint_plan(events[-1], last)[1]
    assert dataset.coverage(last)['full_observed_at'] == scope['full_observed_at']
    assert last['rows'] == []
    assert result['collected'] == (0 if empty else 1)


async def test_explicit_fresh_does_not_use_incremental_filter():
    item = collector([source_row()])
    await item.execute(fresh=True)
    item.query.refresh_plan.assert_not_called()
    assert 'filter' not in item.http.request.call_args.kwargs['params']


def test_delta_business_does_not_replace_complete_coverage():
    row = normalize(source_row())
    previous = dict(coverage=dict(contract=1, count=20, digest=digest(row)))
    envelope = SimpleNamespace(batch_id='b', observed_at=datetime.now(UTC))
    data = dict(page=1, row_count=1)
    state = dataset.archive_state(envelope, data, dict(confirmed=['1']), previous)
    assert state['coverage'] == previous['coverage']
