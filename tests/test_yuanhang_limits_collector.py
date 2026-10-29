import json
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.features.yuanhang_limits.collector import LimitCollector
from empire.features.yuanhang_limits.dataset import LimitDataset
from empire.features.yuanhang_limits.model import member
from tests.prefetch_source import prefetch_http
from tests.test_yuanhang_limits_source import row


def setup_collector(days):
    c = LimitCollector('limit_up_pool')
    state = {'revision': 0, 'cursor': {}}
    events, order = [], []

    async def publish(values, *, expected_revision, cursor, **kwargs):
        assert expected_revision == state['revision']
        order.append('publish')
        events.extend(values)
        state.update(revision=state['revision'] + 1, cursor=deepcopy(cursor))
        return deepcopy(state)

    async def advance(*, expected_revision, cursor, **kwargs):
        assert expected_revision == state['revision']
        state.update(revision=state['revision'] + 1, cursor=deepcopy(cursor))
        return deepcopy(state)

    c.ingest = SimpleNamespace(checkpoint=AsyncMock(side_effect=lambda _: deepcopy(state)),
        ensure_capacity=AsyncMock(), publish_page=publish, advance_checkpoint=advance)
    c.query = SimpleNamespace(collection_plan=AsyncMock(return_value={
        'units': list(days), 'cutoff': days[-1] if days else '2026-07-15', 'remaining': 0}))
    c.http = prefetch_http()
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())

    async def confirm(*args):
        order.append('archive')
        assert len(events) == len(days)
        return {'status': 'complete'}

    c.confirmation = SimpleNamespace(page_status=AsyncMock(side_effect=confirm))

    async def fetch(day, *, reservation=None):
        order.append('fetch')
        raw = row()
        raw['first_limit_up_time'] = None
        return dict(trade_date=day, pool_type=c.pool, filter='HS,GEM2STAR', source_total=1,
                    rows=[member(raw, day)]), datetime.now(UTC)

    c.fetch = AsyncMock(side_effect=fetch)
    return c, state, events, order


@pytest.mark.asyncio
async def test_fetch_publish_continue_before_single_final_archive_wait():
    c, state, events, order = setup_collector(['2026-07-14', '2026-07-15'])
    result = await c.execute()
    assert result['phase'] == 'complete'
    assert order == ['fetch', 'publish', 'fetch', 'publish', 'archive']
    assert all(LimitDataset(c.pool).normalize(e)['row_count'] == 1 for e in events)
    assert c.http.buffer_budget.used == 0


@pytest.mark.asyncio
async def test_failure_does_not_advance_or_wait_for_prior_archive():
    c, state, events, order = setup_collector(['2026-07-14', '2026-07-15'])
    original = c.fetch.side_effect

    async def fail(day, **kwargs):
        if day == '2026-07-15':
            raise ValueError('missing page')
        return await original(day, **kwargs)

    c.fetch.side_effect = fail
    with pytest.raises(ValueError, match='missing page'):
        await c.execute()
    assert state['cursor']['page'] == 1 and len(events) == 1
    assert c.health()['completed_units'] == 1 and c.health()['total_units'] == 2
    assert c.confirmation.page_status.call_count == 0
    c.fetch.side_effect = original
    await c.execute(baseline_revision=state['revision'])
    assert len(events) == 2 and c.http.buffer_budget.used == 0
    assert c.query.collection_plan.call_count == 1


@pytest.mark.asyncio
async def test_empty_plan_has_no_requests_messages_or_archive_wait():
    c, state, events, order = setup_collector([])
    await c.execute()
    assert not order and not events
    assert state['cursor']['phase'] == 'complete'


async def test_multiple_plans_share_one_batch_and_wait_only_after_all_enqueue():
    c, state, events, order = setup_collector(['2026-07-14', '2026-07-15'])
    c.query.collection_plan.side_effect = [
        dict(units=['2026-07-14'], cutoff='2026-07-15', remaining=1),
        dict(units=['2026-07-15'], cutoff='2026-07-15', remaining=0),
    ]
    await c.execute()
    assert order == ['fetch', 'publish', 'fetch', 'publish', 'archive']
    assert len({e.batch_id for e in events}) == 1
    assert [e.raw_payload['page'] for e in events] == [1, 2]
    assert state['cursor']['page'] == 2 and state['cursor']['index'] == 1
    assert c.query.collection_plan.call_args.kwargs['exclude'] == {'2026-07-14', '2026-07-15'}
    assert c.query.collection_plan.call_args.kwargs['through'] == '2026-07-15'


def test_max_bounded_reason_cursor_fits_shared_checkpoint_budget():
    plan = [[f'2026-07-{i % 20 + 1:02}', f'{i:06}.SZ'] for i in range(256)]
    cursor = dict(contract=1, phase='fetch', batch_id='a' * 32, plan=plan,
                  cutoff='2026-07-20', remaining=1000000, page=255)
    assert len(json.dumps(cursor).encode()) < 16384


def test_storage_revalidates_identity_members_and_reason_status():
    from empire.features.yuanhang_limits.storage import pool_payload, reason_payload
    unit = dict(trade_date='2026-07-15', pool_type='limit_up_pool', filter='HS,GEM2STAR',
                source_total=1, rows=[member(row(), '2026-07-15')])
    assert pool_payload(unit) == unit
    unit['rows'][0]['latest'] = '10.150'
    with pytest.raises(ValueError):
        pool_payload(unit)
    with pytest.raises(ValueError):
        reason_payload(dict(trade_date='2026-07-15', unified_code='000001.SZ', name=None,
                            reason_text='无身份正文', reason_kind=None, availability='available'))

@pytest.mark.parametrize('remaining,index,page,total,done,label', [
    (10, 1, 5, 16, 5, '个完整单元'),
    (None, 1, 257, 2, 1, '个单元（当前批）'),
    (0, 2, 258, 258, 258, '个完整单元'),
])
def test_bounded_plan_progress_never_confuses_batch_with_whole_run(remaining,index,page,total,done,label):
    c = LimitCollector('reason')
    c._progress(dict(plan=['a','b'],remaining=remaining,index=index,page=page))
    assert c.health()['completed_units'] == done
    assert c.health()['total_units'] == total
    assert c.health()['unit_name'] == label
