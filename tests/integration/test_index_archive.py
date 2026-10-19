"""Source to shared Redis/archive and formal SQL, private schema per test."""
import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.indices.contract import JOB
from empire.features.indices.dataset import FINGERPRINT_NAMESPACE
from tests.test_ths_indices import CATALOG, envelope
from tests.test_ths_indices import collector as fake_collector

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to private database')]


@pytest.fixture
async def indices():
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    m = build_manager(cfg)
    store = None
    try:
        await m.start('collector.ths_indices')
        c, q, store = m.registry.get('collector.ths_indices'), m.registry.get('indices.query'), m.registry.get('redis.store')
        c.session = SimpleNamespace(headers=lambda _: {})
        c.http = fake_collector().http
        async def publish(e):
            state = await c.ingest.checkpoint(JOB)
            await c.ingest.publish_page([e], job_key=JOB, expected_revision=state['revision'], cursor={'test': True})
            await m.registry.get('archive.worker').flush()
        yield m, c, q, store, publish
    finally:
        await m.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            r = create_client(cfg['redis'])
            keys = [k async for k in r.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                await r.delete(*keys)
            await r.aclose()


async def test_source_archive_query_complete_and_cursor(indices):
    _, c, q, store, _ = indices
    result = await asyncio.wait_for(c.execute(), 15)
    assert result['collected'] == 3 and c.http.request.await_count == 3
    heads = await q.browse(limit=1)
    assert len(heads['rows']) == 1 and heads['next'] == ['1A0001']
    assert (await q.browse(after=heads['next']))['rows'][0]['index_code'] == '399003'
    members = await q.browse('members', '000001')
    assert members['rows'][0]['unified_code'] == '000001.SZ'
    by_index = await q.browse('members', '1A0001', limit=1)
    assert len(by_index['rows']) == 1 and by_index['next']
    following = await q.browse('members', '1A0001', after=by_index['next'])
    assert following['rows'] and all(r['index_code'] == '1A0001' for r in following['rows'])
    assert all(e.status == 'pass' for e in await q.preparation_check())
    assert next(e for e in await q.preparation_check({'purpose': 'historical_signal'}) if e.criterion == 'temporal').status == 'fail'
    assert await store.client.xlen(store.stream) == 0


async def test_cold_hot_revision_late_old_unavailable_and_recovery(indices, monkeypatch):
    m, c, q, store, publish = indices
    class Earlier(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.now(tz) - timedelta(minutes=15)
    monkeypatch.setattr('empire.features.indices.collector.datetime', Earlier)
    await c.execute()
    archive = m.registry.get('archive.worker')
    now = datetime.now(UTC) - timedelta(minutes=10)
    writes = []
    def capture(conn, cursor, sql, params, context, many):
        if 'stock_index' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    try:
        base = envelope().model_copy(update={'observed_at': now})
        original = q.mysql.archive
        counted = AsyncMock(wraps=original)
        monkeypatch.setattr(q.mysql, 'archive', counted)
        await publish(base)
        assert not counted.called and not writes
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, 'ths')
        await publish(base.model_copy(update={'observed_at': now + timedelta(seconds=1)}))
        assert counted.called and not writes
        changed = envelope(members=[['000001', '修订名称'], ['900901', 'B股证券']]).model_copy(update={'observed_at': now + timedelta(seconds=3)})
        await publish(changed)
        assert (await q.browse('members', '900901'))['rows'][0]['unified_code'] == '900901.SH'
        count = len(writes)
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, 'ths')
        await publish(base.model_copy(update={'observed_at': now + timedelta(seconds=2)}))
        assert len(writes) == count and (await q.browse('members', '修订名称'))['rows']
        missing = envelope(available=False, members=[]).model_copy(update={'observed_at': now + timedelta(seconds=4)})
        await publish(missing)
        assert (await q.browse('members', '900901'))['rows'][0]['members_available'] == 0
        from empire.contracts.preparation_catalog import BY_ID
        from empire.plugins.data.preparation import PreparationPlugin

        preparation = PreparationPlugin(q.preparation)
        await preparation.start(q.context)
        for purpose in ('analysis', 'historical_signal'):
            result = await preparation.provider_report(BY_ID['board_history'], q.preparation[0], {}, '',
                                                       {'purpose': purpose})
            data = {e['id']: e for e in result['checks'] if e['phase'] == '数据'}
            assert all(e['status'] != 'unknown' for e in data.values())
            assert data['coverage']['status'] == 'pass' and data['coverage']['blocking']
            assert data['temporal']['status'] == 'fail'
            assert data['temporal']['blocking'] == (purpose == 'historical_signal')
            assert '来源暂无' in data['temporal']['measured']
        await publish(changed.model_copy(update={'observed_at': now + timedelta(seconds=5)}))
        assert all(e.status == 'pass' for e in await q.preparation_check())
        # SQL manual corruption is paired with cache invalidation while archive is stopped.
        async with archive.lock:
            await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, 'ths')
            with q.mysql.engine.begin() as conn:
                conn.execute(text("UPDATE stock_index_member SET unified_code=NULL WHERE source_code='000001'"))
        assert next(e for e in await q.preparation_check() if e.criterion == 'fields').status == 'fail'
        await publish(changed.model_copy(update={'observed_at': now + timedelta(seconds=6)}))
        assert all(e.status == 'pass' for e in await q.preparation_check())
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


async def test_sql_failure_commit_replay_and_success_cleanup(indices, monkeypatch):
    m, c, q, store, publish = indices
    await c.execute()
    archive = m.registry.get('archive.worker')
    await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, 'ths')
    original = q.mysql.archive
    monkeypatch.setattr(q.mysql, 'archive', AsyncMock(side_effect=RuntimeError('SQL unavailable')))
    changed = envelope(members=[['000001', '新版']])
    async with archive.lock:
        state = await c.ingest.checkpoint(JOB)
        await c.ingest.publish_page([changed], job_key=JOB, expected_revision=state['revision'], cursor={'queued': True})
    with pytest.raises(RuntimeError, match='SQL unavailable'):
        await archive.flush()
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(q.mysql, 'archive', original)
    acknowledge = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('Redis ack unavailable')))
    with pytest.raises(RuntimeError, match='Redis ack unavailable'):
        await archive.flush()
    assert (await q.browse('members', '新版'))['rows'] and await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive, 'acknowledge', acknowledge)
    await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, 'ths')
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0


async def test_catalog_revision_retirement_and_cross_index_overlap(indices):
    _, c, q, store, publish = indices
    await c.execute()
    await publish(envelope(code='399003'))
    assert len((await q.browse('members', '000001'))['rows']) == 2
    catalog = [CATALOG[0]]
    e = make_envelope(source='ths', dataset='index.catalog', business_key='catalog', job_key=JOB,
        batch_id='new', run_id='new', payload={'page': 1, 'catalog': catalog})
    await publish(e)
    assert len((await q.browse())['rows']) == 1
    assert len((await q.browse('members', '000001'))['rows']) == 1
    # Reappearance must rebuild members even if their previous content is cached.
    e = make_envelope(source='ths', dataset='index.catalog', business_key='catalog', job_key=JOB,
        batch_id='readd', run_id='readd', payload={'page': 1, 'catalog': CATALOG})
    await publish(e)
    await publish(envelope(code='399003'))
    assert len((await q.browse('members', '000001'))['rows']) == 2
    assert all(e.status == 'pass' for e in await q.preparation_check())
    assert await store.client.xlen(store.stream) == 0


async def test_final_page_does_not_hide_prior_retained_message(indices):
    m, c, _, store, _ = indices
    archive = m.registry.get('archive.worker')
    async with archive.lock:
        task = asyncio.create_task(c.execute())
        async with asyncio.timeout(5):
            while c.stats['status'] != 'awaiting_archive':
                await asyncio.sleep(.01)
        assert c.http.request.await_count == 3 and await store.client.xlen(store.stream) == 3
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    c.http.request.reset_mock()
    await asyncio.wait_for(c.execute(fresh=True), 15)
    assert not c.http.request.called and await store.client.xlen(store.stream) == 0


async def test_catalog_commit_before_scope_reset_failure_replays_safely(indices, monkeypatch):
    m, c, q, store, publish = indices
    await c.execute()
    archive = m.registry.get('archive.worker')
    reset = archive.fingerprints.invalidate
    monkeypatch.setattr(archive.fingerprints, 'invalidate', AsyncMock(side_effect=RuntimeError('reset Redis unavailable')))
    e = make_envelope(source='ths', dataset='index.catalog', business_key='catalog', job_key=JOB,
        batch_id='retire', run_id='retire', payload={'page': 1, 'catalog': [CATALOG[0]]})
    async with archive.lock:
        state = await c.ingest.checkpoint(JOB)
        await c.ingest.publish_page([e], job_key=JOB, expected_revision=state['revision'], cursor={'retire': True})
    with pytest.raises(RuntimeError, match='reset Redis unavailable'):
        await archive.flush()
    assert await store.client.xlen(store.stream) == 1
    assert len((await q.browse())['rows']) == 1
    monkeypatch.setattr(archive.fingerprints, 'invalidate', reset)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    e = make_envelope(source='ths', dataset='index.catalog', business_key='catalog', job_key=JOB,
        batch_id='restore', run_id='restore', payload={'page': 1, 'catalog': CATALOG})
    await publish(e)
    await publish(envelope(code='399003', members=[['200012', '样本证券']]))
    assert (await q.browse('members', '200012'))['rows']
    assert all(e.status == 'pass' for e in await q.preparation_check())
