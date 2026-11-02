from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.features.yuanhang_limits.collector import LimitCollector
from scripts.migrate_yuanhang_ten_day import JOBS, PRICE_JOB, upgrade
from tests.test_yuanhang_limits_collector import setup_collector


@pytest.mark.parametrize('job', JOBS)
@pytest.mark.parametrize('phase', ['fetch', 'awaiting_archive', 'complete'])
def test_conversion_preserves_queued_batch_and_never_forges_completion(job, phase):
    native = job == PRICE_JOB
    old = dict(contract=1, phase='collecting' if native and phase == 'fetch' else phase,
               batch_id='original-batch', page=2242, pages=2242, scope='all', plan=['old'],
               next_index=42, next_year=2020, current_plan={'mode': 'full'})
    saved = deepcopy(old)
    new = upgrade(old, job)
    assert old == saved
    assert new['phase'] == old['phase'] and new['batch_id'] == old['batch_id']
    assert new['pages'] == new['page'] == 2242
    assert new['contract'] == 2
    if phase == 'fetch':
        assert new['replan_recent']
        if native:
            assert new['next_index'] == 0 and 'current_plan' not in new
        else:
            assert new['plan'] == [] and new['scope'] == 'recent'
    assert upgrade(new, job) == new


async def test_migrated_batch_appends_recent_without_losing_old_confirmation():
    c, state, events, _ = setup_collector(['2026-11-02'])
    state['cursor'] = upgrade(dict(contract=1, phase='fetch', batch_id='old-batch',
        page=2242, index=10, plan=['2021-03-22'], scope='all', cutoff='2026-11-02'), c.job_key)
    await c.execute()
    assert len(events) == 1 and events[0].batch_id == 'old-batch'
    assert events[0].raw_payload['page'] == 2243
    assert c.confirmation.page_status.call_args.args[-2:] == ('old-batch', 2243)


async def test_backfill_stops_after_one_plan_even_when_more_history_is_missing():
    c, state, events, order = setup_collector(['2026-07-14'])
    c.query.collection_plan.return_value.update(remaining=1000, pending=['2026-07-15'])
    await c.execute(maintenance_scope='backfill')
    assert len(events) == 1 and order == ['fetch', 'publish', 'archive']
    assert c.query.collection_plan.await_count == 1
    assert state['cursor']['remaining'] == 1000
    assert c.stats['completed_units'] == c.stats['total_units'] == 1
    assert c.stats['remaining_units'] == 1000


def test_backfill_progress_counts_current_batch_separately_from_remaining_history():
    c, *_ = setup_collector([])
    c._progress(dict(page=7, index=7, plan=['2026-01-01'] * 64,
                     remaining=8000, scope='backfill'))
    assert c.stats['completed_units'] == 7 and c.stats['total_units'] == 64
    assert c.stats['remaining_units'] == 8000


@pytest.mark.parametrize('old_scope', ['recent', 'backfill'])
async def test_reason_previous_day_resume_runs_current_recent_before_backfill(old_scope):
    c = LimitCollector('reason', scope='recent')
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(return_value=dict(revision=4)))
    c.query = SimpleNamespace(collection_plan=AsyncMock(return_value=dict(
        cutoff='2026-11-02', units=[['2026-11-02', '000001.SZ']])))
    stages = []
    async def execute(**kwargs):
        stages.append(kwargs.get('scope'))
        c.stats.update(requests=len(stages), response_bytes=1, wire_bytes=1,
                       queued_messages=1, queued_bytes=1, collected=1)
        return dict(phase='complete', cutoff='2026-10-30' if len(stages) == 1 else '2026-11-02',
                    scope=old_scope if len(stages) == 1 else kwargs['scope'])
    c._execute = execute
    result = await c.execute()
    assert stages == [None, 'recent', 'backfill']
    assert result['cutoff'] == '2026-11-02' and c.stats['requests'] == 6
