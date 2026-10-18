import asyncio
import copy
import json
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.plugins.datasets.financial_statements import KINDS, parse
from empire.plugins.datasets.financial_wire import SCHEMA_VERSION, pack_rows
from tests.prefetch_source import prefetch_http
from tests.test_ths_statements import STOCK, large_source, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


@pytest.fixture(params=list(KINDS))
async def financial_db(request, monkeypatch):
    kind = request.param
    cfg = copy.deepcopy(load_config())
    token = uuid4().hex
    cfg['redis']['namespace'] = 'empire:test:' + token
    manager = build_manager(cfg)
    query = manager.entries['data.' + kind].plugin
    collector = manager.entries['collector.ths_' + kind].plugin
    query.source = collector.source = 'ths'
    mysql = store = None
    try:
        await manager.start('collector.ths_' + kind)
        mysql, store = manager.registry.get('mysql.store'), manager.registry.get('redis.store')
        monkeypatch.setattr(query, '_securities', lambda conn: [STOCK])
        collector.http = prefetch_http(request=AsyncMock(side_effect=lambda *a, **k:
            httpx.Response(200, json=source(kind))), response_policy=lambda x: x)
        async def publish(body=None, observed=None):
            rows = parse(kind, body or source(kind), STOCK)
            state = await collector.ingest.checkpoint(collector.job_key)
            batch = uuid4().hex
            value = make_envelope(source=query.source, dataset=kind + '.statement', business_key='SH:601139',
                job_key=collector.job_key, run_id=batch, batch_id=batch,
                schema_version=SCHEMA_VERSION,
                payload={'page': 1, 'unit': 'SH:601139', 'rows': pack_rows(rows), 'manifest': None})
            if observed:
                value = value.model_copy(update={'observed_at': observed})
            await collector.ingest.publish_page([value], job_key=collector.job_key,
                expected_revision=state['revision'], cursor={'test': batch})
            await manager.registry.get('archive.worker').flush()
            return value
        yield manager, query, collector, publish
    finally:
        await manager.stop('pipeline.archive', cascade=True)
        if mysql:
            def cleanup():
                with mysql.engine.begin() as conn:
                    conn.execute(text(f'DELETE FROM {query.table}'), {'source': query.source})
                    conn.execute(text('DELETE FROM collection_state WHERE namespace=:namespace'),
                                 {'namespace': cfg['redis']['namespace']})
            await mysql.control(cleanup)
        if store:
            keys = [k async for k in store.client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith('empire:test:' + token + ':') for k in keys)
                await store.client.delete(*keys)
        await manager.shutdown()


async def test_source_to_query_completion_temporal_limit(financial_db):
    manager, query, collector, _ = financial_db
    result = await asyncio.wait_for(collector.execute(), 15)
    assert result['collected'] == 2 and collector.http.request.await_count == 1
    assert len(await query.list_statements('601139')) == 2
    assert await query.list_statements('601') == await query.list_statements('601139')
    assert await query.list_statements('601139', 1, 1) == (await query.list_statements('601139'))[1:]
    assert await query.list_statements('999999') == []
    checks = {c.criterion: c.status for c in await query.preparation_check()}
    assert checks == dict(fields='pass', keys='pass', coverage='pass', quality='pass', freshness='pass', temporal='fail')
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0


async def test_large_matrix_uses_default_limit_without_partial_checkpoint(financial_db):
    manager, query, collector, _ = financial_db
    body = large_source(query.kind)
    expected = parse(query.kind, body, STOCK)
    collector.http.request = AsyncMock(side_effect=lambda *a, **k: httpx.Response(200, json=body))
    before = await collector.ingest.checkpoint(collector.job_key)
    original_limit = collector.ingest.settings.get('max_page_bytes', 524288)
    collector.ingest.settings['max_page_bytes'] = 1024
    try:
        with pytest.raises(ValueError, match='byte limit'):
            await collector.execute()
        assert await collector.ingest.checkpoint(collector.job_key) == before
        assert not await query.list_statements()
    finally:
        collector.ingest.settings['max_page_bytes'] = original_limit
    await asyncio.wait_for(collector.execute(), 20)
    assert await query.list_statements('601139', 500) == expected
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0


async def test_nonquarter_period_source_to_formal_query(financial_db):
    manager, query, collector, publish = financial_db
    body = source(query.kind)
    matrix = json.loads(body['flashData'])
    matrix['report'][0] = ['2014-07-31', '2014-06-30']
    body['flashData'] = json.dumps(matrix)
    await publish(body)
    rows = await query.list_statements('601139')
    assert {r['report_date'] for r in rows} == {'2014-07-31', '2014-06-30'}
    assert await manager.registry.get('redis.store').client.xlen(
        manager.registry.get('redis.store').stream) == 0


async def test_missing_source_values_archive_but_do_not_pass_preparation(financial_db):
    manager, query, collector, _ = financial_db
    from empire.plugins.datasets.financial_statements import REQUIRED
    body = source(query.kind)
    matrix = json.loads(body['flashData'])
    matrix['report'][1][0] = False
    body['flashData'] = json.dumps(matrix)
    collector.http.request = AsyncMock(side_effect=lambda *a, **k: httpx.Response(200, json=body))
    result = await asyncio.wait_for(collector.execute(), 15)
    assert result['phase'] == 'complete'
    rows = await query.list_statements('601139')
    assert len(rows) == 2 and rows[0]['fields'][REQUIRED[query.kind][0]] is None
    checks = {c.criterion: c.status for c in await query.preparation_check()}
    assert checks['coverage'] == 'pass' and checks['fields'] == 'fail'
    assert await manager.registry.get('redis.store').client.xlen(
        manager.registry.get('redis.store').stream) == 0
    # Nullable source contents are stable on both hot and cold fingerprint paths.
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if query.table in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(query.mysql.engine, 'before_cursor_execute', capture)
    try:
        await collector.execute(baseline_revision=await collector.checkpoint_revision())
        await manager.registry.get('archive.worker').fingerprints.invalidate('ths_' + query.kind, query.source)
        await collector.execute(baseline_revision=await collector.checkpoint_revision())
        assert not writes
    finally:
        event.remove(query.mysql.engine, 'before_cursor_execute', capture)
    # Source correction repairs required data through the same normal round.
    collector.http.request = AsyncMock(side_effect=lambda *a, **k: httpx.Response(200, json=source(query.kind)))
    await collector.execute(baseline_revision=await collector.checkpoint_revision())
    assert all(c.status == 'pass' for c in await query.preparation_check() if c.criterion != 'temporal')


async def test_source_arithmetic_quality_is_separate_from_coverage(financial_db):
    manager, query, collector, _ = financial_db
    if query.kind != 'balance':
        return  # Arithmetic source variants for income/cashflow are covered in source tests.
    body = source('balance')
    matrix = json.loads(body['flashData'])
    matrix['report'][1][0] = '8.00亿'
    body['flashData'] = json.dumps(matrix)
    collector.http.request = AsyncMock(side_effect=lambda *a, **k: httpx.Response(200, json=body))
    await collector.execute()
    checks = {c.criterion: c.status for c in await query.preparation_check()}
    assert checks['coverage'] == checks['fields'] == 'pass'
    assert checks['quality'] == 'fail'


async def test_hot_cold_revision_old_and_repair(financial_db, monkeypatch):
    manager, query, collector, publish = financial_db
    archive, mysql = manager.registry.get('archive.worker'), manager.registry.get('mysql.store')
    early = datetime.now(UTC) - timedelta(minutes=10)
    await publish(observed=early)
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and query.table in statement:
            writes.append(statement)
    event.listen(mysql.engine, 'before_cursor_execute', capture)
    try:
        original = mysql.archive
        calls = []
        async def counted(records):
            calls.append(1)
            return await original(records)
        monkeypatch.setattr(mysql, 'archive', counted)
        await publish(observed=early + timedelta(minutes=1))
        assert not calls and not writes
        await archive.fingerprints.invalidate('ths_' + query.kind, query.source)
        await publish(observed=early + timedelta(minutes=2))
        assert calls and not writes
        revised = source(query.kind)
        f = json.loads(revised['flashData'])
        # Optional new source field changes contents for all three statement kinds.
        f['title'].append(['补充金额', '元', 2, False, True])
        f['report'].append(['10.00', '20.00'])
        revised['flashData'] = json.dumps(f)
        await publish(revised, early + timedelta(minutes=4))
        assert len(writes) == 2
        expected = await query.list_statements()
        await archive.fingerprints.invalidate('ths_' + query.kind, query.source)
        await publish(observed=early + timedelta(minutes=3))
        assert await query.list_statements() == expected and len(writes) == 2
        async with archive.lock:
            await archive.fingerprints.invalidate('ths_' + query.kind, query.source)
            with mysql.engine.begin() as conn:
                conn.execute(text(f'UPDATE {query.table} SET payload=JSON_OBJECT()'),
                             {'source': query.source})
        assert any(c.status == 'fail' for c in await query.preparation_check())
        await publish(revised, early + timedelta(minutes=5))
        assert await query.list_statements() == expected
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', capture)


async def test_commit_then_ack_failure_retains_and_replays(financial_db, monkeypatch):
    manager, query, collector, publish = financial_db
    archive, store = manager.registry.get('archive.worker'), manager.registry.get('redis.store')
    original = archive.acknowledge
    async def fail(ids):
        raise RuntimeError('test acknowledgment failure')
    monkeypatch.setattr(archive, 'acknowledge', fail)
    with pytest.raises(RuntimeError, match='acknowledgment'):
        await publish()
    assert await store.client.xlen(store.stream) == 1
    assert len(await query.list_statements()) == 2
    monkeypatch.setattr(archive, 'acknowledge', original)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0


async def test_late_archive_all_units_queued_before_wait(financial_db, monkeypatch):
    manager, query, collector, _ = financial_db
    second = {**STOCK, 'code': '601140'}
    monkeypatch.setattr(query, '_securities', lambda conn: [STOCK, second])
    archive, store = manager.registry.get('archive.worker'), manager.registry.get('redis.store')
    async with archive.lock:
        task = asyncio.create_task(collector.execute())
        for _ in range(100):
            if collector.stats['status'] == 'awaiting_archive':
                break
            await asyncio.sleep(.02)
        assert collector.http.request.await_count == 2
        assert await store.client.xlen(store.stream) == 3
        assert not task.done()
    await asyncio.wait_for(task, 10)


async def test_invalid_response_preserves_cursor(financial_db):
    manager, query, collector, _ = financial_db
    before = await collector.ingest.checkpoint(collector.job_key)
    collector.http.request = AsyncMock(return_value=httpx.Response(200, json={'flashData': '{}'}))
    with pytest.raises(ValueError):
        await collector.execute()
    assert await collector.ingest.checkpoint(collector.job_key) == before


async def test_resume_starts_at_unpublished_security(financial_db, monkeypatch):
    manager, query, collector, _ = financial_db
    second = {**STOCK, 'code': '601140'}
    monkeypatch.setattr(query, '_securities', lambda conn: [STOCK, second])
    original = collector.fetch
    async def interrupted(stock, **options):
        if stock['code'] == second['code']:
            raise asyncio.CancelledError()
        return await original(stock, **options)
    monkeypatch.setattr(collector, 'fetch', interrupted)
    with pytest.raises(asyncio.CancelledError):
        await collector.execute()
    checkpoint = await collector.ingest.checkpoint(collector.job_key)
    assert checkpoint['cursor']['index'] == 1
    # Presentation order and names do not change the stable ordered scope.
    monkeypatch.setattr(query, '_securities', lambda conn: [second, {**STOCK, 'name': '新名称'}])
    monkeypatch.setattr(collector, 'fetch', original)
    collector.http.request.reset_mock()
    await asyncio.wait_for(collector.execute(baseline_revision=checkpoint['revision']), 10)
    assert collector.http.request.await_count == 1
    assert '601140' in collector.http.request.call_args.args[1]


@pytest.mark.parametrize('change', ['add_before_cursor', 'remove_completed', 'same_count_new_key'])
async def test_scope_change_rebuilds_complete_round_and_keeps_old_queue(financial_db, monkeypatch, change):
    from empire.plugins.datasets.financial_statements import digest
    manager, query, collector, _ = financial_db
    second, third = {**STOCK, 'code': '601140'}, {**STOCK, 'code': '601138'}
    monkeypatch.setattr(query, '_securities', lambda conn: [STOCK, second])
    original = collector.fetch
    async def interrupted(stock, **options):
        if stock['code'] == second['code']:
            raise asyncio.CancelledError()
        return await original(stock, **options)
    monkeypatch.setattr(collector, 'fetch', interrupted)
    archive, store = manager.registry.get('archive.worker'), manager.registry.get('redis.store')
    async with archive.lock:
        with pytest.raises(asyncio.CancelledError):
            await collector.execute()
        before = await collector.ingest.checkpoint(collector.job_key)
        assert before['cursor']['index'] == 1 and await store.client.xlen(store.stream) == 1
        changed = {'add_before_cursor': [third, STOCK, second],
                   'remove_completed': [second], 'same_count_new_key': [third, second]}[change]
        monkeypatch.setattr(query, '_securities', lambda conn: changed)
        # A failed first unit cannot overwrite even the superseded checkpoint.
        monkeypatch.setattr(collector, 'fetch', AsyncMock(side_effect=ValueError('test first unit failure')))
        with pytest.raises(ValueError, match='first unit failure'):
            await collector.execute(baseline_revision=before['revision'])
        assert await collector.ingest.checkpoint(collector.job_key) == before
        assert await store.client.xlen(store.stream) == 1
        monkeypatch.setattr(collector, 'fetch', original)
        collector.http.request.reset_mock()
        task = asyncio.create_task(collector.execute(baseline_revision=before['revision']))
        try:
            for _ in range(200):
                if collector.stats['status'] == 'awaiting_archive':
                    break
                if task.done():
                    await task
                await asyncio.sleep(.02)
            current = await collector.ingest.checkpoint(collector.job_key)
            assert current['cursor']['phase'] == 'awaiting_archive'
            assert current['cursor']['batch_id'] != before['cursor']['batch_id']
            assert current['cursor']['scope_hash'] == digest([s['market'] + ':' + s['code'] for s in changed])
            assert current['cursor']['collected'] == 2 * len(changed)
            assert collector.http.request.await_count == len(changed)
            assert await store.client.xlen(store.stream) == len(changed) + 2
            assert not task.done()  # Old pending units do not serialize new downloads.
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # An already fully queued round finishes without reading a newer pool.
            monkeypatch.setattr(query, 'securities', AsyncMock(side_effect=AssertionError('must finish queued round')))
            task = asyncio.create_task(collector.execute(baseline_revision=current['revision']))
            await asyncio.sleep(.05)
            assert not task.done()
        except BaseException:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            raise
    result = await asyncio.wait_for(task, 15)
    assert result['phase'] == 'complete'
    assert await store.client.xlen(store.stream) == 0
    for stock in [STOCK, *changed]:
        assert len(await query.list_statements(stock['code'])) == 2


async def test_scope_rebuild_interrupted_resumes_new_batch(financial_db, monkeypatch):
    manager, query, collector, _ = financial_db
    from empire.plugins.datasets.financial_statements import digest
    first, second = {**STOCK, 'code': '601138'}, {**STOCK, 'code': '601140'}
    old = dict(phase='fetch', batch_id='old', index=1, pages=1, collected=2,
               units=2, scope_hash=digest(['SH:601139', 'SH:601140']), rolling=digest([]))
    await collector.ingest.advance_checkpoint(job_key=collector.job_key, expected_revision=0, cursor=old)
    monkeypatch.setattr(query, '_securities', lambda conn: [first, second])
    original = collector.fetch
    async def interrupted(stock, **options):
        if stock['code'] == second['code']:
            raise asyncio.CancelledError()
        return await original(stock, **options)
    monkeypatch.setattr(collector, 'fetch', interrupted)
    with pytest.raises(asyncio.CancelledError):
        await collector.execute(baseline_revision=1)
    state = await collector.ingest.checkpoint(collector.job_key)
    assert state['cursor']['batch_id'] != 'old' and state['cursor']['index'] == 1
    assert state['cursor']['pages'] == 1 and state['cursor']['collected'] == 2
    monkeypatch.setattr(collector, 'fetch', original)
    collector.http.request.reset_mock()
    result = await asyncio.wait_for(collector.execute(baseline_revision=state['revision']), 15)
    assert result['batch_id'] == state['cursor']['batch_id'] and result['phase'] == 'complete'
    assert collector.http.request.await_count == 1 and '601140' in collector.http.request.call_args.args[1]
    assert len(await query.list_statements(first['code'])) == len(await query.list_statements(second['code'])) == 2


async def test_sql_failure_retains_message(financial_db, monkeypatch):
    manager, query, collector, publish = financial_db
    mysql, store = manager.registry.get('mysql.store'), manager.registry.get('redis.store')
    original = mysql.archive
    monkeypatch.setattr(mysql, 'archive', AsyncMock(side_effect=RuntimeError('test SQL unavailable')))
    with pytest.raises(RuntimeError, match='SQL unavailable'):
        await publish()
    assert await store.client.xlen(store.stream) == 1
    assert await query.list_statements() == []
    monkeypatch.setattr(mysql, 'archive', original)
    await manager.registry.get('archive.worker').flush()
    assert await store.client.xlen(store.stream) == 0
    assert len(await query.list_statements()) == 2


async def test_unchanged_cache_proof_refreshes_freshness_without_sql(financial_db, monkeypatch):
    manager, query, collector, _ = financial_db
    await asyncio.wait_for(collector.execute(), 10)
    result = await query.mysql.read(query._audit)
    complete, _, count, actual, observed, findings = result
    monkeypatch.setattr(query, '_audit', lambda: (complete, False, count, actual, observed - timedelta(days=4), findings))
    checks = {e.criterion: e.status for e in await query.preparation_check()}
    assert checks['freshness'] == 'pass'
    await manager.registry.get('archive.worker').fingerprints.invalidate('ths_' + query.kind, query.source)
    checks = {e.criterion: e.status for e in await query.preparation_check()}
    assert checks['freshness'] == 'fail' and checks['coverage'] == 'pass'
    # A changed business set cannot be hidden by a fresh proof.
    changed = {**actual, 'digest': '0' * 64}
    monkeypatch.setattr(query, '_audit', lambda: (False, False, count, changed, observed, findings))
    assert any(e.criterion == 'coverage' and e.status == 'fail' for e in await query.preparation_check())


async def test_checkpoint_loss_rechecks_source_without_business_dml(financial_db):
    manager, query, collector, _ = financial_db
    await asyncio.wait_for(collector.execute(), 10)
    store, mysql = manager.registry.get('redis.store'), manager.registry.get('mysql.store')
    key = collector.ingest._checkpoint_key(collector.job_key)
    assert key.startswith('empire:test:')
    await store.client.delete(key)
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if query.table in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(mysql.engine, 'before_cursor_execute', capture)
    try:
        collector.http.request.reset_mock()
        await asyncio.wait_for(collector.execute(), 10)
        assert collector.http.request.await_count == 1 and not writes
        assert len(await query.list_statements()) == 2
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', capture)


async def test_scoped_financial_acceptance_proves_content_and_use(financial_db):
    manager, query, collector, _ = financial_db
    await collector.execute()
    request = dict(codes=['601139'], start='2025-10-01', end='2025-12-31', purpose='analysis')
    checks = {c.criterion:c for c in await query.preparation_check(request)}
    assert checks['coverage'].status == 'pass' and '1 份报表' in checks['coverage'].measured
    assert checks['fields'].status == 'pass' and checks['quality'].status == 'pass'
    assert checks['temporal'].status == 'fail' and not checks['temporal'].blocking
    request['purpose'] = 'historical_signal'
    assert next(c for c in await query.preparation_check(request) if c.criterion == 'temporal').blocking
    request['codes'] = ['999999']
    missing = next(c for c in await query.preparation_check(request) if c.criterion == 'coverage')
    assert missing.status == 'fail' and missing.findings[0]['code'] == '999999'
    request['codes'] = ['601139']
    unavailable = {c.criterion: c for c in await query.preparation_check(
        dict(request, start='2024-01-01', end='2024-12-31'))}
    assert unavailable['keys'].status == 'pass'
    assert unavailable['coverage'].status == 'unknown'
    assert '来源在所选范围未返回报告期' in unavailable['coverage'].findings[0]['message']
    # Keep row count, dates and SQL proof; tamper content outside the selected range.
    # A subset must not use the unchanged count to authorize a corrupt unit.
    from sqlalchemy import text
    def corrupt():
        with query.mysql.engine.begin() as conn:
            conn.execute(text(f'UPDATE {query.table} SET payload=JSON_SET(payload, :path, :value) '
                'WHERE report_date=:day'),
                dict(path='$.name', value='篡改名称', source=query.source, day='2025-09-30'))
    cache = manager.registry.get('archive.worker').fingerprints
    await manager.stop('pipeline.archive', cascade=True)
    await cache.invalidate('ths_' + query.kind, query.source)
    await query.mysql.control(corrupt)
    checks = {c.criterion:c for c in await query.preparation_check(request)}
    assert checks['coverage'].status == 'fail' and checks['coverage'].findings
