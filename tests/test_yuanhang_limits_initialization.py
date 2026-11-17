import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from scripts.initialize_yuanhang_limits import complete_history, require_owned_pending


async def test_initialization_pending_scan_only_accepts_owned_jobs():
    store = SimpleNamespace(stream='test:ingest', client=SimpleNamespace(xrange=AsyncMock(side_effect=[
        [('1-0', {'envelope': json.dumps(dict(job_key='ths-yuanhang-limit-up-pool-v1'))})], []])))
    await require_owned_pending(store)
    assert store.client.xrange.call_args.kwargs['min'] == '(1-0'
    store.client.xrange = AsyncMock(return_value=[('2-0', {'envelope': json.dumps(dict(job_key='sina-news-v1'))})])
    with pytest.raises(RuntimeError, match='非本次'):
        await require_owned_pending(store)


@pytest.mark.parametrize('scope', ['recent', 'backfill'])
async def test_full_history_resumes_bounded_cursor_then_drains_all(scope):
    collector = SimpleNamespace(checkpoint_revision=AsyncMock(side_effect=[11, 76]),
        execute=AsyncMock(side_effect=[
            dict(cutoff='2026-11-04', phase='complete', scope=scope, remaining=8000),
            dict(cutoff='2026-11-04', phase='complete', scope='all', remaining=0)]),
        health=lambda: dict(requests=64))
    result, rounds = await complete_history(collector, '2026-11-04')
    assert result['scope'] == 'all' and len(rounds) == 2
    assert [call.kwargs for call in collector.execute.await_args_list] == [
        dict(baseline_revision=revision, history_only=True, maintenance_scope='all')
        for revision in (11, 76)]


@pytest.mark.parametrize('result,message', [
    (dict(cutoff='2026-11-03', phase='complete', scope='backfill', remaining=0), '截止日'),
    (dict(cutoff='2026-11-04', phase='awaiting_archive', scope='all', remaining=0), '归档确认'),
    (dict(cutoff='2026-11-04', phase='complete', scope='all', remaining=1), '待采单元'),
])
async def test_full_history_rejects_incomplete_or_different_range(result, message):
    collector = SimpleNamespace(checkpoint_revision=AsyncMock(return_value=1),
        execute=AsyncMock(return_value=result), health=lambda: {})
    with pytest.raises(RuntimeError, match=message):
        await complete_history(collector, '2026-11-04')
    assert collector.execute.await_count == 1


async def test_long_audit_keeps_completed_cursor_and_round_evidence(tmp_path, monkeypatch):
    import asyncio

    from scripts import initialize_yuanhang_limits as initialization

    real_sleep = asyncio.sleep

    async def progress_tick(_):
        await real_sleep(0)

    async def slow_audit(_):
        # Allow multiple progress ticks while the audit is running.
        for _ in range(4):
            await real_sleep(0)
        return [SimpleNamespace(criterion='coverage', status='pass', measured='complete')]

    query = SimpleNamespace(read=AsyncMock(return_value=dict(database_name='test', server_uuid='test')),
                            collection_plan=AsyncMock(return_value=dict(cutoff='2026-11-04')))
    plugins = {'yuanhang.limits.query': query,
               'redis.store': SimpleNamespace(stream='test:ingest', client=SimpleNamespace(
                   xrange=AsyncMock(return_value=[]), xlen=AsyncMock(return_value=0)))}
    for kind in [*initialization.POOLS, 'reason']:
        setattr(query, 'check_' + kind, slow_audit)
        plugins['collector.yuanhang_limits_' + kind] = SimpleNamespace(project_id=kind,
            execute=AsyncMock(return_value=dict(cutoff='2026-11-04', phase='complete', scope='all', remaining=0)),
            checkpoint_revision=AsyncMock(return_value=1), health=lambda: dict(status='complete', collected=0))
    manager = SimpleNamespace(start=AsyncMock(), shutdown=AsyncMock(), registry=SimpleNamespace(get=plugins.get))
    monkeypatch.setattr(initialization, 'load_config', lambda _: {'redis': {'namespace': 'test'}})
    monkeypatch.setattr(initialization, 'build_manager', lambda _: manager)
    monkeypatch.setattr(initialization, 'acquire_instance_lock', lambda: SimpleNamespace(unlock=lambda: None))
    monkeypatch.setattr(initialization.asyncio, 'sleep', progress_tick)
    report = tmp_path / 'full-history.json'
    await initialization.run(SimpleNamespace(config=None, apply=True, report=str(report),
        request_retries=2, through='2026-11-04', pools_only=False))
    result = json.loads(report.read_text('utf8'))
    assert result['complete'] and result['pending'] == 0
    for state in result['projects'].values():
        assert state['cursor']['scope'] == 'all' and state['cursor']['remaining'] == 0
        assert len(state['execution_rounds']) == 1
        assert state['audit'][0]['status'] == 'pass'
