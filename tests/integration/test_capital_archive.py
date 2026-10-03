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
from empire.plugins.collectors.tdx_capital_source import parse
from empire.plugins.datasets.capital_actions import KINDS, SCHEMA_VERSIONS
from tests.capital_samples import STOCK, issue_detail, source, with_issue_detail

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]


async def test_replan_retains_old_queue_and_confirms_only_new_complete_scope(capital_db):
    manager, query, collector, _ = capital_db
    if query.kind == 'dividends':
        return  # Pool changes are covered by the stock-scope lifecycle regression.
    archive, store = manager.registry.get('archive.worker'), manager.registry.get('redis.store')
    publish = collector.ingest.publish_page
    async def stop(*args, **kw):
        await publish(*args, **kw)
        raise asyncio.CancelledError
    revised = source(query.kind, amount=7)
    async with archive.lock:
        collector.ingest.publish_page = stop
        with pytest.raises(asyncio.CancelledError):
            await collector.execute()
        old = await collector.ingest.checkpoint(collector.job_key)
        assert await store.client.xlen(store.stream) == 1
        collector.http.request.side_effect = lambda *a, **kw: httpx.Response(200,
            json=issue_detail(revised) if a[1].endswith('tdxsj_xgzx_zfmx') else revised)
        with pytest.raises(asyncio.CancelledError):
            await collector.execute(baseline_revision=old['revision'])
        new = await collector.ingest.checkpoint(collector.job_key)
        assert new['cursor']['batch_id'] != old['cursor']['batch_id']
        assert new['cursor']['collected'] == 1
        assert await store.client.xlen(store.stream) == 2  # No clearing an old pending batch.
        collector.ingest.publish_page = publish
    await archive.flush()
    await asyncio.wait_for(collector.execute(baseline_revision=new['revision']), 15)
    expected = parse(query.kind, revised, 10000)[0]
    if query.kind == 'additional_issues':
        with_issue_detail(expected, revised)
    assert await query.list_events() == expected
    assert all(check.status == 'pass' for check in await query.preparation_check())
    assert await store.client.xlen(store.stream) == 0


async def test_changed_scope_does_not_reuse_old_ready_proof(capital_db):
    manager, query, collector, _ = capital_db
    if query.kind == 'dividends':
        return  # The SQL audit directly checks the current stock pool.
    await collector.execute()
    assert all(check.status == 'pass' for check in await query.preparation_check())
    before = await collector.ingest.checkpoint(collector.job_key)
    body = source(query.kind)
    added = copy.deepcopy(body['ResultSets'][0]['Content'][0])
    if query.kind == 'additional_issues':
        added[1], added[15] = '688111', 1002
    else:
        added[12], added[10] = '688111', '700002'
    body['ResultSets'][0].update(Content=[body['ResultSets'][0]['Content'][0], added], Count=2)
    body['ResultSets'][2]['Content'] = [[2]]
    collector.http.request.side_effect = lambda *a, **kw: httpx.Response(200,
        json=issue_detail() if a[1].endswith('tdxsj_xgzx_zfmx') else body)
    original = collector.ingest.publish_page
    async def stop(*args, **kw):
        await original(*args, **kw)
        raise asyncio.CancelledError
    collector.ingest.publish_page = stop
    with pytest.raises(asyncio.CancelledError):
        await collector.execute(baseline_revision=before['revision'])
    await manager.registry.get('archive.worker').flush()
    assert len(await query.list_events()) == 1
    assert any(check.status == 'fail' for check in await query.preparation_check())
    collector.ingest.publish_page = original
    collector.http.request.side_effect = lambda *a, **kw: httpx.Response(200,
        json=issue_detail(source(query.kind, code='688111')) if a[1].endswith('tdxsj_xgzx_zfmx') else body)
    state = await collector.ingest.checkpoint(collector.job_key)
    await asyncio.wait_for(collector.execute(baseline_revision=state['revision']), 15)
    assert len(await query.list_events()) == 2
    assert all(check.status == 'pass' for check in await query.preparation_check())


async def test_forced_round_reuses_verified_unavailable_and_refreshes_next_round(capital_db):
    manager, query, collector, _ = capital_db
    if query.kind != 'additional_issues':
        return
    body = source(query.kind)
    added = copy.deepcopy(body['ResultSets'][0]['Content'][0])
    added[1], added[15] = '688111', 1002
    body['ResultSets'][0].update(Content=[body['ResultSets'][0]['Content'][0], added], Count=2)
    body['ResultSets'][2]['Content'] = [[2]]
    good = issue_detail(source(query.kind, code='688111'))
    collector.http.request.side_effect = [httpx.Response(200, json=body),
        httpx.Response(200, json={'ErrorCode': -1005}), httpx.Response(200, json=good)]
    original = collector.ingest.publish_page
    async def stop(*args, **kw):
        await original(*args, **kw)
        raise asyncio.CancelledError
    collector.ingest.publish_page = stop
    with pytest.raises(asyncio.CancelledError):
        await collector.execute(fresh=True)
    collector.ingest.publish_page = original
    archive = manager.registry.get('archive.worker')
    await archive.flush()
    state = await collector.ingest.checkpoint(collector.job_key)
    assert state['cursor']['detail_refresh_all'] is True
    assert len(await query.list_events()) == 1
    errors = await collector.records.list_error_summaries(collector.project_id)
    assert errors['total'] == 0
    assert (await query.list_events())[0]['data']['detail']['availability'] == 'unavailable'
    sql = manager.registry.get('mysql.store')
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if query.table in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(sql.engine, 'before_cursor_execute', capture)
    try:
        collector.http.request.side_effect = [httpx.Response(200, json=body), httpx.Response(200, json=good)]
        calls = collector.http.request.await_count
        await collector.execute(baseline_revision=state['revision'])
        await archive.flush()
        assert collector.http.request.await_count == calls + 2
        assert len(writes) == 1  # The second plan is newly inserted.
        assert (await collector.records.list_error_summaries(collector.project_id))['total'] == 0
        assert (await collector.ingest.checkpoint(collector.job_key))['cursor']['phase'] == 'complete'
        assert all(check.status == 'pass' for check in await query.preparation_check())
        store = manager.registry.get('redis.store')
        assert await store.client.xlen(store.stream) == 0
        writes.clear()
        collector.http.request.side_effect = [httpx.Response(200, json=body),
            httpx.Response(200, json={'ErrorCode': -1005})]
        state = await collector.ingest.checkpoint(collector.job_key)
        calls = collector.http.request.await_count
        await collector.execute(baseline_revision=state['revision'])
        await archive.flush()
        assert collector.http.request.await_count == calls + 2  # List and the unavailable ID only.
        assert len(await query.list_events()) == 2
        assert not writes and await store.client.xlen(store.stream) == 0
    finally:
        event.remove(sql.engine, 'before_cursor_execute', capture)


async def test_independent_security_archives_before_failed_frontier_is_repaired(capital_db, monkeypatch):
    manager, query, collector, _ = capital_db
    if query.kind == 'rights_issues':
        return  # There is no per-security source request in the rights collector.
    stocks = [STOCK, {**STOCK, 'code': '688111'}]
    monkeypatch.setattr(query, '_securities', lambda conn: stocks)
    body = source(query.kind)
    if query.kind == 'additional_issues':
        alias = copy.deepcopy(body['ResultSets'][0]['Content'][0])
        alias[1] = '688111'
        body['ResultSets'][0]['Content'].append(alias)
        body['ResultSets'][0]['Count'] = 2
        alias[15] = 1002
        body['ResultSets'][2]['Content'] = [[2]]
        alias_body = source(query.kind, code='688111')
        alias_body['ResultSets'][0]['Content'][0][15] = 1002
        replies = [httpx.Response(200, json=body), httpx.Response(200, json={'ErrorCode': -1006}),
                   httpx.Response(200, json=issue_detail(alias_body))]
    else:
        replies = [httpx.Response(200, json={'ErrorCode': -1005}), httpx.Response(200, json=body)]
    collector.http.request.side_effect = replies
    with pytest.raises(ValueError):
        await collector.execute()
    await manager.registry.get('archive.worker').flush()
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0
    assert len(await query.list_events(code='688111')) == 1
    assert await query.list_events(code='688110') == []
    state = await collector.ingest.checkpoint(collector.job_key)
    assert state['cursor']['index'] == 0
    assert any(check.status == 'fail' for check in await query.preparation_check())
    collector.http.request.side_effect = [httpx.Response(200, json=body)] * 2 if query.kind == 'dividends' else [
        httpx.Response(200, json=body), httpx.Response(200, json=issue_detail()),
        httpx.Response(200, json=issue_detail(alias_body))]
    await asyncio.wait_for(collector.execute(baseline_revision=state['revision']), 15)
    assert len(await query.list_events()) == 2
    assert all(check.status == 'pass' for check in await query.preparation_check())
    assert await store.client.xlen(store.stream) == 0


@pytest.fixture(params=list(KINDS))
async def capital_db(request, monkeypatch):
    kind = request.param
    cfg = copy.deepcopy(load_config())
    token = uuid4().hex
    test_source = 'tdx'
    cfg['redis']['namespace'] = 'empire:test:' + token
    manager = build_manager(cfg)
    query = manager.entries['data.' + kind].plugin
    collector = manager.entries['collector.tdx_' + kind].plugin
    query.source = collector.source = test_source
    mysql = store = None
    try:
        await manager.start('collector.tdx_' + kind)
        mysql, store = manager.registry.get('mysql.store'), manager.registry.get('redis.store')
        monkeypatch.setattr(query, '_securities', lambda conn: [STOCK])
        collector.http = SimpleNamespace(request=AsyncMock(side_effect=lambda *a, **k:
            httpx.Response(200, json=issue_detail() if a[1].endswith('tdxsj_xgzx_zfmx') else source(kind))),
            response_policy=lambda profile: profile)
        async def publish(body=None, observed=None):
            rows, _ = parse(kind, body or source(kind), 10000, STOCK if kind == 'dividends' else None)
            if kind == 'additional_issues':
                with_issue_detail(rows, body)
            state = await collector.ingest.checkpoint(collector.job_key)
            batch = uuid4().hex
            value = make_envelope(source=test_source, dataset=kind + '.unit',
                schema_version=SCHEMA_VERSIONS[kind],
                business_key='SH:688110', job_key=collector.job_key, run_id=batch, batch_id=batch,
                payload={'page': 1, 'unit': 'SH:688110', 'rows': rows, 'manifest': None})
            if observed:
                value = value.model_copy(update={'observed_at': observed})
            await collector.ingest.publish_page([value], job_key=collector.job_key,
                expected_revision=state['revision'], cursor={'test': batch, 'schema_version': SCHEMA_VERSIONS[kind]})
            await manager.registry.get('archive.worker').flush()
            return value
        yield manager, query, collector, publish
    finally:
        await manager.stop('pipeline.archive', cascade=True)
        if mysql:
            def cleanup():
                with mysql.engine.begin() as conn:
                    conn.execute(text(f'DELETE FROM {query.table}'), {'source': test_source})
                    conn.execute(text('DELETE FROM collection_state WHERE namespace=:namespace'),
                                 {'namespace': cfg['redis']['namespace']})
            await mysql.control(cleanup)
        if store:
            keys = [k async for k in store.client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith('empire:test:' + token + ':') for k in keys)
                await store.client.delete(*keys)
        await manager.shutdown()


async def test_source_to_collector_redis_archive_query_and_manifest(capital_db):
    manager, query, collector, _ = capital_db
    result = await asyncio.wait_for(collector.execute(), 15)
    assert result['collected'] == 1
    rows = await query.list_events(code='688110')
    assert len(rows) == 1 and rows[0]['market'] == 'SH'
    assert all(c.status == 'pass' for c in await query.preparation_check())
    assert await manager.registry.get('redis.store').client.xlen(manager.registry.get('redis.store').stream) == 0
    assert await query.list_events(code='000001') == []


async def test_repeat_hot_cold_revision_old_response_and_missing_fields(capital_db, monkeypatch):
    manager, query, collector, publish = capital_db
    archive, mysql = manager.registry.get('archive.worker'), manager.registry.get('mysql.store')
    store = manager.registry.get('redis.store')
    earlier = datetime.now(UTC) - timedelta(minutes=10)
    await publish(observed=earlier)
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
        await publish(observed=earlier + timedelta(minutes=1))
        assert not calls and not writes
        await archive.fingerprints.invalidate(query.kind, query.source)
        await publish(observed=earlier + timedelta(minutes=2))
        assert calls and not writes
        revised = source(query.kind, amount=8)
        if query.kind == 'dividends':
            revised = source(query.kind)
            revised['ResultSets'][0]['Content'][0][9] = 2  # EPS correction, same payout plan.
        await publish(revised, earlier + timedelta(minutes=4))
        assert len(writes) == 1
        new = await query.list_events()
        await archive.fingerprints.invalidate(query.kind, query.source)
        await publish(observed=earlier + timedelta(minutes=3))
        assert await query.list_events() == new and len(writes) == 1
        assert await store.client.xlen(store.stream) == 0
        # Explicit test-only corruption, with writer stopped and cache invalidated.
        async with archive.lock:
            await archive.fingerprints.invalidate(query.kind, query.source)
            with mysql.engine.begin() as conn:
                conn.execute(text(f"UPDATE {query.table} SET payload=JSON_OBJECT()"), {'source': query.source})
        assert any(c.status == 'fail' for c in await query.preparation_check())
        await publish(revised, earlier + timedelta(minutes=5))
        assert await query.list_events() == new
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', capture)


async def test_sql_commit_then_ack_failure_replays_without_business_dml(capital_db, monkeypatch):
    manager, query, collector, publish = capital_db
    archive = manager.registry.get('archive.worker')
    store = manager.registry.get('redis.store')
    original = archive.acknowledge
    async def fail(ids):
        raise RuntimeError('synthetic Redis acknowledgment failure')
    monkeypatch.setattr(archive, 'acknowledge', fail)
    with pytest.raises(RuntimeError, match='acknowledgment'):
        await publish()
    assert len(await query.list_events()) == 1
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive, 'acknowledge', original)
    mysql = manager.registry.get('mysql.store')
    writes = []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if query.table in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(statement)
    event.listen(mysql.engine, 'before_cursor_execute', capture)
    try:
        await archive.flush()
        assert not writes
    finally:
        event.remove(mysql.engine, 'before_cursor_execute', capture)
    assert await store.client.xlen(store.stream) == 0
    assert len(await query.list_events()) == 1


async def test_sql_failure_retains_valid_queue_until_replay(capital_db, monkeypatch):
    manager, query, collector, publish = capital_db
    mysql, store = manager.registry.get('mysql.store'), manager.registry.get('redis.store')
    archive = manager.registry.get('archive.worker')
    original = mysql.archive
    monkeypatch.setattr(mysql, 'archive', AsyncMock(side_effect=RuntimeError('synthetic SQL failure')))
    with pytest.raises(RuntimeError, match='SQL failure'):
        await publish()
    assert await store.client.xlen(store.stream) == 1
    assert await query.list_events() == []
    monkeypatch.setattr(mysql, 'archive', original)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0 and len(await query.list_events()) == 1


async def test_cache_freshness_cannot_hide_missing_sql_content(capital_db):
    manager, query, collector, _ = capital_db
    await asyncio.wait_for(collector.execute(), 15)
    archive, mysql = manager.registry.get('archive.worker'), manager.registry.get('mysql.store')
    async with archive.lock:
        # Keep the proof deliberately to verify preparation always compares real SQL.
        with mysql.engine.begin() as conn:
            conn.execute(text(f'DELETE FROM {query.table}'), {'source': query.source})
    assert any(c.status == 'fail' for c in await query.preparation_check())


async def test_unknown_schema_isolates_only_registered_project(capital_db):
    manager, query, collector, _ = capital_db
    store, archive = manager.registry.get('redis.store'), manager.registry.get('archive.worker')
    value = make_envelope(source=query.source, dataset=query.kind + '.unit', schema_version=99,
        business_key='unknown', job_key=collector.job_key, run_id='test', batch_id='test', payload={})
    # Future-schema fixture enters the shared stream explicitly to exercise consumer isolation.
    await store.client.xadd(store.stream, {'envelope': value.model_dump_json()})
    await archive.flush()
    assert not archive.blocked and collector.project_id in archive.blocked_projects
    assert await store.client.xlen(store.stream) == 1


async def test_parallel_same_date_dividends_survive_full_pipeline(capital_db):
    manager, query, collector, _ = capital_db
    if query.kind != 'dividends':
        return  # This source shape belongs exclusively to dividend details.
    body = source('dividends', amount=8)
    body['ResultSets'][0]['Content'].append(source('dividends', amount=5)['ResultSets'][0]['Content'][0])
    body['ResultSets'][0]['Count'] = 2
    collector.http.request.side_effect = lambda *a, **k: httpx.Response(200, json=body)
    result = await collector.execute()
    assert result['collected'] == 2
    assert {r['data']['cash_per_share'] for r in await query.list_events()} == {'0.8', '0.5'}
    assert all(c.status == 'pass' for c in await query.preparation_check())
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0


async def test_dividend_identity_migration_retains_business_and_observations(capital_db):
    manager, query, collector, publish = capital_db
    if query.kind != 'dividends':
        return
    from empire.plugins.datasets.capital_actions import digest
    from empire.plugins.infra.collection_state import read_state
    from scripts.migrate_dividend_identity import migrate_rows
    await publish()
    original = (await query.list_events())[0]
    data = original['data']
    legacy = digest([original['market'], original['code'], data['report_date'], data['announcement_date']])
    mysql, archive = manager.registry.get('mysql.store'), manager.registry.get('archive.worker')
    async with archive.lock:
        await archive.fingerprints.invalidate('dividends', query.source)
        with mysql.engine.begin() as conn:
            conn.execute(text('UPDATE dividend_plan SET record_key=:key'),
                         dict(key=legacy, source=query.source))
            before = read_state(conn, query.namespace, query.project_id, query.source)
        report = migrate_rows(mysql.engine, query.namespace, query.source)
    assert report['before'] == report['after'] and report['changed_keys'] == 1
    assert (await query.list_events())[0] == original
    with mysql.engine.connect() as conn:
        after = read_state(conn, query.namespace, query.project_id, query.source)
    assert after['contract_version'] == 2 and 'manifest' not in after and 'progress' not in after
    assert after['units']['SH:688110']['observed_at'] == before['units']['SH:688110']['observed_at']
    with pytest.raises(ValueError, match='显式维护'):
        await query.mysql.read(query._require_dividend_identity)


async def test_issue_detail_backfill_migration_and_detail_only_revision(capital_db):
    manager, query, collector, _ = capital_db
    if query.kind != 'additional_issues':
        return
    from empire.plugins.infra.collection_state import read_state, save_state
    from scripts.migrate_issue_availability import migrate_rows
    await collector.execute()
    mysql, archive = manager.registry.get('mysql.store'), manager.registry.get('archive.worker')
    initial = (await query.list_events())[0]
    async with archive.lock:
        await archive.fingerprints.invalidate(query.kind, query.source)
        with mysql.engine.begin() as conn:
            conn.execute(text("UPDATE additional_issue SET payload=JSON_REMOVE(payload,'$.detail')"),
                         {'source': query.source})
            old = read_state(conn, query.namespace, query.project_id, query.source, lock=True)
            save_state(conn, query.namespace, query.project_id, query.source, query.kind + '.unit',
                       {**old, 'contract_version': 1}, old)
        report = migrate_rows(mysql.engine, query.namespace, query.source)
        assert report['before'] == report['after'] and report['reset_required']
        with pytest.raises(ValueError, match='显式维护'):
            await query.mysql.read(query._require_issue_contract)
        with mysql.engine.begin() as conn:
            pending = read_state(conn, query.namespace, query.project_id, query.source, lock=True)
            assert 'manifest' not in pending and 'progress' not in pending
            assert pending['units']['SH:688110']['observed_at'] == old['units']['SH:688110']['observed_at']
            save_state(conn, query.namespace, query.project_id, query.source, query.kind + '.unit',
                       {k: v for k, v in pending.items() if k != 'detail_migration_pending'}, pending)
    assert any(v.status == 'fail' for v in await query.preparation_check())
    state = await collector.ingest.checkpoint(collector.job_key)
    await collector.execute(baseline_revision=state['revision'])
    assert (await query.list_events())[0] == initial
    body = issue_detail()
    fields = body['ResultSets'][0]['ColName']
    body['ResultSets'][0]['Content'][0][fields.index('T109')] = '修订后的发行对象'
    collector.http.request.side_effect = lambda *a, **kw: httpx.Response(200,
        json=body if a[1].endswith('tdxsj_xgzx_zfmx') else source(query.kind))
    state = await collector.ingest.checkpoint(collector.job_key)
    calls = collector.http.request.await_count
    await collector.execute(baseline_revision=state['revision'])
    assert collector.http.request.await_count == calls + 1
    assert (await query.list_events())[0] == initial
    state = await collector.ingest.checkpoint(collector.job_key)
    await collector.execute(fresh=True, baseline_revision=state['revision'])
    revised = (await query.list_events())[0]
    assert revised['data']['detail']['issue_targets'] == '修订后的发行对象'
    assert revised['record_key'] == initial['record_key']
    assert all(v.status == 'pass' for v in await query.preparation_check())
    assert await manager.registry.get('redis.store').client.xlen(manager.registry.get('redis.store').stream) == 0
