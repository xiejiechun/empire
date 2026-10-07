"""Source HTML → shared Redis/SQL archive → formal query, in UUID-owned scope."""

import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.plugins.datasets.industries import FINGERPRINT_NAMESPACE, JOB
from tests.prefetch_source import prefetch_http
from tests.test_ths_industries import SNAPSHOT, member_page, response

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


@pytest.fixture
async def industry_db():
    cfg = copy.deepcopy(load_config())
    token = uuid4().hex
    cfg['redis']['namespace'] = 'empire:test:' + token
    manager = build_manager(cfg)
    query = manager.entries['data.industries'].plugin
    collector = manager.entries['collector.ths_industries'].plugin
    query.source = collector.source = 'ths'
    mysql = store = None
    try:
        await manager.start('collector.ths_industries')
        mysql, store = manager.registry.get('mysql.store'), manager.registry.get('redis.store')
        collector.session = SimpleNamespace(headers=lambda _: {})
        collector.http = prefetch_http(request=AsyncMock(side_effect=lambda method, url, **kw: response(url)),
                                         response_policy=lambda _: None)
        async def publish(data=None, observed=None):
            batch = uuid4().hex
            envelope = make_envelope(source=query.source, dataset='industry.snapshot', business_key='current',
                job_key=JOB, batch_id=batch, run_id=batch, payload={'page': 1, 'industries': data or SNAPSHOT})
            if observed:
                envelope = envelope.model_copy(update={'observed_at': observed})
            state = await collector.ingest.checkpoint(JOB)
            await collector.ingest.publish_page([envelope], job_key=JOB, expected_revision=state['revision'],
                                                cursor={'test': batch})
            await manager.registry.get('archive.worker').flush()
            return envelope
        yield manager, query, collector, publish
    finally:
        await manager.stop('pipeline.archive', cascade=True)
        if mysql:
            def cleanup():
                with mysql.engine.begin() as conn:
                    for table in ('industry_member', 'industry'):
                        conn.execute(text(f'DELETE FROM {table}'), {'source': query.source})
                    conn.execute(text('DELETE FROM collection_state WHERE namespace=:namespace'),
                                 {'namespace': cfg['redis']['namespace']})
            await mysql.control(cleanup)
        if store:
            keys = [k async for k in store.client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith('empire:test:' + token + ':') for k in keys)
                await store.client.delete(*keys)
        await manager.shutdown()


async def test_source_to_formal_query_and_preparation(industry_db):
    manager, query, collector, _ = industry_db
    result = await asyncio.wait_for(collector.execute(), 15)
    assert result['collected'] == 2 and collector.http.request.await_count == 2
    rows = await query.list_members()
    assert rows['industry_count'] == 1 and rows['total'] == 2
    assert (await query.list_members('银行'))['total'] == 2
    assert (await query.list_members('600000'))['total'] == 1
    assert (await query.list_members('', 1, 1))['rows'][0]['code'] == '600000'
    assert all(c.status == 'pass' for c in await query.preparation_check())
    assert next(c for c in await query.preparation_check({'purpose': 'historical_signal'})
                if c.criterion == 'temporal').status == 'fail'
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0


async def test_large_complete_response_to_formal_key_set(industry_db):
    manager, query, collector, _ = industry_db
    codes = [f'000{i:03d}' for i in range(1, 277)]
    body = member_page(codes).replace('<span class="page_info">1/1</span>',
                                     '<div class="m-pager"></div>')
    collector.http.request.side_effect = [response('https://q.10jqka.com.cn/thshy/'),
                                         httpx.Response(200, content=body.encode('gbk'))]
    result = await asyncio.wait_for(collector.execute(), 15)
    assert result['collected'] == 276 and result['requests'] == 2
    assert '/page/1/size/1000/' in collector.http.request.call_args.args[1]
    rows = await query.list_members(limit=500)
    assert [r['code'] for r in rows['rows']] == codes and rows['total'] == 276
    assert all(c.status == 'pass' for c in await query.preparation_check())
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0


@pytest.mark.parametrize('body', [member_page(pages=14), member_page(['000001', '000001'])])
async def test_ignored_size_or_same_count_duplicate_preserves_old_set(industry_db, body):
    manager, query, collector, publish = industry_db
    await publish()
    before = await collector.ingest.checkpoint(collector.job_key)
    collector.http.request.side_effect = [response('https://q.10jqka.com.cn/thshy/'),
                                         httpx.Response(200, content=body.encode('gbk'))]
    with pytest.raises(ValueError):
        await collector.execute()
    assert await collector.ingest.checkpoint(collector.job_key) == before
    rows = await query.list_members()
    assert [r['code'] for r in rows['rows']] == ['000001', '600000']
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0


async def test_hot_cold_same_content_revisions_removal_stale_and_repair(industry_db, monkeypatch):
    manager, query, collector, publish = industry_db
    archive, mysql = manager.registry.get('archive.worker'), query.mysql
    start = datetime.now(UTC) - timedelta(minutes=15)
    await publish(observed=start)
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'industry' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(mysql.engine, 'before_cursor_execute', capture)
    try:
        original = mysql.archive
        calls = []
        async def counted(records):
            calls.append(1)
            return await original(records)
        monkeypatch.setattr(mysql, 'archive', counted)
        await publish(observed=start + timedelta(minutes=1))
        assert not calls and not writes
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        await publish(observed=start + timedelta(minutes=2))
        assert calls and not writes
        changed = [dict(code='881156', name='保险', members=[['600000', '新名称']])]
        await publish(changed, start + timedelta(minutes=4))
        rows = await query.list_members()
        assert rows['total'] == 1 and rows['rows'][0]['industry_code'] == '881156'
        count = len(writes)
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        await publish(observed=start + timedelta(minutes=3))
        assert await query.list_members() == rows and len(writes) == count
        async with archive.lock:
            await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
            with mysql.engine.begin() as conn:
                conn.execute(text("UPDATE industry_member SET name=''"), {'source': query.source})
        assert next(c for c in await query.preparation_check() if c.criterion == 'fields').status == 'fail'
        await publish(changed, start + timedelta(minutes=5))
        assert (await query.list_members())['rows'] == rows['rows']
        assert all(c.status == 'pass' for c in await query.preparation_check())
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', capture)


async def test_sql_failure_and_commit_ack_replay(industry_db, monkeypatch):
    manager, query, collector, publish = industry_db
    archive, store = manager.registry.get('archive.worker'), manager.registry.get('redis.store')
    original = query.mysql.archive
    monkeypatch.setattr(query.mysql, 'archive', AsyncMock(side_effect=RuntimeError('SQL test failure')))
    with pytest.raises(RuntimeError, match='SQL test failure'):
        await publish()
    assert await store.client.xlen(store.stream) == 1
    assert (await query.list_members())['total'] == 0
    monkeypatch.setattr(query.mysql, 'archive', original)
    acknowledge = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ack test failure')))
    with pytest.raises(RuntimeError, match='ack test failure'):
        await archive.flush()
    assert (await query.list_members())['total'] == 2 and await store.client.xlen(store.stream) == 1
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if 'industry' in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(query.mysql.engine, 'before_cursor_execute', capture)
    try:
        monkeypatch.setattr(archive, 'acknowledge', acknowledge)
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        await archive.flush()
        assert not writes and await store.client.xlen(store.stream) == 0
    finally:
        event.remove(query.mysql.engine, 'before_cursor_execute', capture)


async def test_cancel_after_queue_resume_without_network(industry_db):
    manager, query, collector, _ = industry_db
    archive, store = manager.registry.get('archive.worker'), manager.registry.get('redis.store')
    async with archive.lock:
        task = asyncio.create_task(collector.execute())
        for _ in range(100):
            if collector.stats['status'] == 'awaiting_archive':
                break
            await asyncio.sleep(.02)
        assert collector.http.request.await_count == 2 and await store.client.xlen(store.stream) == 1
        assert not task.done()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    collector.http.request.reset_mock()
    await asyncio.wait_for(collector.execute(fresh=True), 10)
    assert not collector.http.request.called and (await query.list_members())['total'] == 2


async def test_cache_cannot_hide_same_count_wrong_key_or_missing_relation(industry_db):
    manager, query, collector, publish = industry_db
    await publish()
    archive = manager.registry.get('archive.worker')
    async with archive.lock:
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        with query.mysql.engine.begin() as conn:
            conn.execute(text("UPDATE industry_member SET unified_code='600001.SH' WHERE unified_code='600000.SH'"),
                         {'source': query.source})
    assert next(c for c in await query.preparation_check() if c.criterion == 'coverage').status == 'fail'
    await publish()
    assert all(c.status == 'pass' for c in await query.preparation_check())
    async with archive.lock:
        await archive.fingerprints.invalidate(FINGERPRINT_NAMESPACE, query.source)
        with query.mysql.engine.begin() as conn:
            conn.execute(text('DELETE FROM industry'), {'source': query.source})
    with pytest.raises(ValueError, match='关联'):
        await query.preparation_check()
    await publish()
    assert all(c.status == 'pass' for c in await query.preparation_check())


async def test_lost_redis_checkpoint_rebuilds_complete_current_set(industry_db):
    manager, query, collector, _ = industry_db
    await collector.execute()
    store = manager.registry.get('redis.store')
    checkpoint_key = collector.ingest._checkpoint_key(JOB)
    await store.client.delete(checkpoint_key)
    collector.http.request.reset_mock()
    await collector.execute(baseline_revision=await collector.checkpoint_revision())
    assert collector.http.request.await_count == 2
    assert (await query.list_members())['total'] == 2
    assert await store.client.xlen(store.stream) == 0
