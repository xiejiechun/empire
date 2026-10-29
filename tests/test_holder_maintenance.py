"""Request-cost and persistent source-defect counterexamples."""
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from empire.contracts.collector import NEXT_MAINTENANCE_DUE, CollectionSourceGap
from tests.test_holder_identity_gaps import mixed_bonds
from tests.test_ths_holders import STOCK, configured, source


def stock(code):
    return {**STOCK, 'code': code, 'unified_code': code + '.SH'}


async def run(c, **kwargs):
    return await c.execute(baseline_revision=await c.checkpoint_revision(), **kwargs)


async def test_unchanged_second_pass_zero_requests_and_new_security_only():
    c = configured()
    await run(c)
    requests, messages = c.http.request.await_count, len(c.ingest.events)
    await run(c)
    assert c.http.request.await_count == requests and len(c.ingest.events) == messages
    c.query.securities.return_value = [STOCK, stock('601140')]
    await run(c)
    assert c.http.request.await_count == requests + 1
    assert c.ingest.events[-1].raw_payload['unit'] == '601140.SH'
    assert c.stats['processed_units'] == c.stats['total_units'] == 1


async def test_source_defect_does_not_freeze_tail_or_refetch_same_period():
    c = configured([STOCK, stock('601140'), stock('601141')])
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200, content=(
        mixed_bonds() if STOCK['code'] in url else source(url.split('/')[-2])).encode('gb18030'))
    with pytest.raises(CollectionSourceGap, match='持续来源缺陷'):
        await run(c)
    checkpoint = (await c.ingest.checkpoint(c.job_key))['cursor']
    assert checkpoint['index'] == 3 and checkpoint['phase'] == 'source_gap'
    assert c.stats['failed_units'] == 0
    with pytest.raises(CollectionSourceGap, match='同周期无需反复点击'):
        await run(c)
    assert c.http.request.await_count == 3 and len(c.ingest.events) == 3
    assert c.stats['processed_units'] == 0 and c.stats['source_gap_units'] == 1
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(
        200, content=source(url.split('/')[-2]).encode('gb18030'))
    await run(c, fresh=True)
    assert c.stats['status'] == 'complete' and not c.stats['notice']


async def test_real_failure_retries_only_unconfirmed_unit():
    c = configured([STOCK, stock('601140'), stock('601141')])
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200, content=source(
        '000000' if '601140' in url else url.split('/')[-2]).encode('gb18030'))
    with pytest.raises(ValueError, match='1只证券来源校验失败'):
        await run(c)
    assert c.ingest.state['cursor']['index'] == 1
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(
        200, content=source(url.split('/')[-2]).encode('gb18030'))
    await run(c)
    assert c.http.request.await_count == 4
    assert c.ingest.events[-1].raw_payload['unit'] == '601140.SH'


async def test_checkpoint_loss_uses_confirmed_units_and_due_only():
    c = configured([STOCK, stock('601140')])
    await run(c)
    c.ingest.state = {'revision': 0, 'cursor': {}}
    await run(c)
    assert c.http.request.await_count == 2
    original = c.query.collection_units.side_effect
    async def older(now):
        units = await original(now)
        units[STOCK['unified_code']]['stamp'] = now - timedelta(days=2)
        return units
    c.query.collection_units.side_effect = older
    await run(c)
    assert c.http.request.await_count == 3


async def test_saved_interval_honored_and_force_refresh_discovers_revision():
    c = configured()
    await run(c)
    token = NEXT_MAINTENANCE_DUE.set(lambda stamp: stamp + 1)
    try:
        original = c.query.collection_units.side_effect
        async def older(now):
            units = await original(now)
            units[STOCK['unified_code']]['stamp'] = now - timedelta(seconds=2)
            return units
        c.query.collection_units.side_effect = older
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(
            200, content=source(name='修订').encode('gb18030'))
        await run(c)
        assert c.http.request.await_count == 2
        assert c.ingest.events[-2].raw_payload['reports']['top_holders'][0]['members'][0]['holder_name'] == '修订0'
    finally:
        NEXT_MAINTENANCE_DUE.reset(token)


async def test_old_checkpoint_rejected_without_network_or_implicit_conversion():
    c = configured()
    c.ingest.state = {'revision': 1, 'cursor': {'phase': 'fetch', 'source_gap': '601139.SH'}}
    with pytest.raises(ValueError, match='显式维护'):
        await run(c)
    assert c.http.request.await_count == 0
    assert c.ingest.state['cursor'] == {'phase': 'fetch', 'source_gap': '601139.SH'}


def test_gap_recheck_time_uses_saved_daily_schedule():
    from empire.features.holders.planning import gap_notice
    from empire.plugins.collection.control import next_due
    policy = dict(enabled=True, mode='daily', daily_time='20:00')
    token = NEXT_MAINTENANCE_DUE.set(lambda stamp: next_due(policy, stamp))
    try:
        notice, securities, reports = gap_notice({'601139.SH': dict(
            stamp=datetime(2026, 10, 28, 3, tzinfo=UTC), gap_count=2)}, 0)
        assert '2026-10-28 20:00' in notice and (securities, reports) == (1, 2)
    finally:
        NEXT_MAINTENANCE_DUE.reset(token)


@pytest.mark.parametrize('damage', ['none', 'different_hash', 'old', 'future', 'missing', 'unavailable', 'no_sql_hash'])
async def test_only_matching_fingerprint_can_advance_sql_confirmation(monkeypatch, damage):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from empire.features.holders.dataset import HolderDataset
    from empire.features.holders.planning import confirmed_units
    now = datetime.now(UTC)
    old = now - timedelta(days=2)
    proof = dict(contract=4, count=3, digest='a'*64, gap_count=1,
                 observed_at=old.isoformat(timespec='microseconds'), fingerprint_hash='b'*64)
    if damage == 'no_sql_hash':
        proof.pop('fingerprint_hash')
    stamp = old - timedelta(days=1) if damage == 'old' else now + timedelta(days=1) if damage == 'future' else now
    cached = {STOCK['unified_code']: dict(hash='c'*64 if damage == 'different_hash' else 'b'*64,
                                        version=[stamp.isoformat(timespec='microseconds')])}
    peek = AsyncMock(return_value={} if damage == 'missing' else cached)
    if damage == 'unavailable':
        peek.side_effect = RuntimeError('cache offline')
    monkeypatch.setattr('empire.features.holders.planning.FingerprintCache', lambda *a: SimpleNamespace(peek=peek))
    query = SimpleNamespace(mysql=SimpleNamespace(read=AsyncMock(return_value={STOCK['unified_code']: proof})),
        context=SimpleNamespace(optional=lambda _: object()), mapping=HolderDataset(), archive_settings={})
    result = await confirmed_units(query, now)
    assert result[STOCK['unified_code']]['stamp'] == (now if damage == 'none' else old)
    assert result[STOCK['unified_code']]['gap_count'] == 1


def test_explicit_checkpoint_migration_only_retires_known_old_format():
    from scripts.migrate_holder_checkpoint import upgrade
    old = dict(phase='fetch', index=1853, source_gap='300398.SZ')
    assert upgrade(old) == {} and old['index'] == 1853
    assert upgrade(dict(format=2, phase='source_gap')) == dict(format=2, phase='source_gap')
    for invalid in ([], {'format': 3}, {'phase': 'unknown'}):
        with pytest.raises(ValueError):
            upgrade(invalid)


@pytest.mark.parametrize('outcome', ['complete', 'gap', 'failure'])
async def test_shared_control_supplies_saved_schedule_without_context_leak(outcome):
    from tests.test_collection_control import setup
    control, source, _, http = await setup()
    policy = control.state['jobs']['stocks']['policy']
    policy.update(enabled=True, mode='interval', interval_seconds=300)
    async def execute(**kwargs):
        assert NEXT_MAINTENANCE_DUE.get()(1000) == 1300
        if outcome == 'gap':
            raise CollectionSourceGap('source defect')
        if outcome == 'failure':
            raise ValueError('invalid source')
        return {}
    source.execute = execute
    try:
        await control.run('stocks')
        await control.tasks['stocks']
        assert NEXT_MAINTENANCE_DUE.get() is None
        assert control.state['history'][0]['status'] == {'complete': 'complete', 'gap': 'source_gap', 'failure': 'error'}[outcome]
    finally:
        await control.stop()
        await http.close()
