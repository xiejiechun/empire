"""Monthly source→Redis→shared archive→formal query, replay and historical repair."""
import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from tests.prefetch_source import prefetch_http
from tests.test_tdx_shareholder_changes import KIND, PERIOD, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to private SQL/Redis')]


@pytest.fixture
async def monthly(monkeypatch):
    cfg = copy.deepcopy(load_config())
    manager, store = build_manager(cfg), None
    monkeypatch.setattr('empire.features.performance.collector.monthly_plan', lambda _: [PERIOD])
    monkeypatch.setattr('empire.features.performance.query.monthly_plan', lambda _: [PERIOD])
    try:
        await manager.start('collector.tdx_' + KIND)
        c, q = manager.registry.get('collector.tdx_' + KIND), manager.registry.get(KIND + '.tdx_query')
        store = manager.registry.get('redis.store')
        c.http = prefetch_http(request=AsyncMock(side_effect=lambda *a, **k: httpx.Response(200, json=source(duplicate=True))), response_policy=lambda _: None)
        yield manager, c, q, store
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            prefix = cfg['redis']['namespace'] + ':'
            keys = [k async for k in client.scan_iter(match=prefix + '*')]
            assert all(k.startswith(prefix) for k in keys)
            if keys:
                await client.delete(*keys)
            await client.aclose()


async def collect(c):
    return await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision()), 25)


async def test_duplicate_facts_query_filters_hot_cold_revision_stale_replay(monthly):
    manager, c, q, store = monthly
    await collect(c)
    assert len((await q.list_records())['rows']) == 3
    assert len((await q.list_records(code='600000', start='2025-08-15', end='2025-08-15'))['rows']) == 2
    page = await q.list_records(limit=1)
    assert page['next'] and (await q.list_records(after=page['next'], limit=1))['rows'][0]['record_key'] != page['rows'][0]['record_key']
    checks = {v.criterion: v.status for v in await q.preparation_check()}
    assert checks['coverage'] == checks['keys'] == checks['fields'] == checks['temporal'] == 'pass'
    archive = manager.registry.get('archive.worker')
    dml, calls = [], []
    def capture(conn, cursor, statement, parameters, context, executemany):
        if q.table in statement and statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            dml.append(statement)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    original = q.mysql.archive
    async def counted(records):
        calls.append(records)
        return await original(records)
    q.mysql.archive = counted
    try:
        await collect(c)
        assert not dml and not calls
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        await collect(c)
        assert not dml and calls
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=source(revised=True))
        await collect(c)
        assert dml and len((await q.list_records())['rows']) == 2  # Withdrawn duplicate removed.
        from empire.features.performance.source import parse
        rows = [r for r in parse(KIND, source(revised=True), PERIOD)[0] if r['unified_code'].endswith('SH')]
        prior = c.envelope(PERIOD+'|SH', rows, 1, 'replay', datetime.now(UTC))
        before = len(dml)
        stale = prior.model_copy(update={'observed_at': datetime.now(UTC)-timedelta(days=1)})
        assert (await archive._archive_data(stale, q.mapping.normalize(stale)))['written_count'] == 0
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
        assert (await archive._archive_data(prior, q.mapping.normalize(prior)))['written_count'] == 0
        assert len(dml) == before and await store.client.xlen(store.stream) == 0
    finally:
        q.mysql.archive = original
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


@pytest.mark.parametrize('failure', ['sql', 'ack'])
async def test_transaction_or_ack_failure_preserves_and_replays(monthly, monkeypatch, failure):
    manager, c, q, store = monthly
    archive = manager.registry.get('archive.worker')
    owner, method = (q.mysql, 'archive') if failure == 'sql' else (archive, 'acknowledge')
    original, attempted = getattr(owner, method), asyncio.Event()
    async def fail(*args, **kw):
        attempted.set()
        raise RuntimeError('owned test failure')
    monkeypatch.setattr(owner, method, fail)
    task = asyncio.create_task(collect(c))
    try:
        await asyncio.wait_for(attempted.wait(), 10)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert await store.client.xlen(store.stream) > 0
        monkeypatch.setattr(owner, method, original)
        archive.request_flush()
        await collect(c)
        assert await store.client.xlen(store.stream) == 0
        assert len((await q.list_records())['rows']) == 3
        await store.client.delete(c.ingest._checkpoint_key(c.job_key))
        await collect(c)
        assert len((await q.list_records())['rows']) == 3
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_completed_history_same_count_wrong_set_and_missing_required_field_repaired(monthly):
    manager, c, q, store = monthly
    await collect(c)
    cache = manager.registry.get('archive.worker').fingerprints
    await cache.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'tdx')
    def damage():
        with q.mysql.engine.begin() as conn:
            conn.execute(text("UPDATE shareholder_change SET actor='' LIMIT 1"))
    await q.mysql.control(damage)
    assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'fail'
    await collect(c)
    assert next(v for v in await q.preparation_check() if v.criterion == 'coverage').status == 'pass'
    assert await store.client.xlen(store.stream) == 0


async def test_source_month_precision_and_unknown_quantity_separate_collection_from_quality(monthly):
    _,c,q,store=monthly
    body=source()
    body['ResultSets'][0]['Content'][0][9]=201011
    body['ResultSets'][0]['Content'][0][4]=None
    c.http.request.side_effect=lambda *a,**kw: httpx.Response(200,json=body)
    await collect(c)
    rows=(await q.list_records(code='600000'))['rows']
    assert rows[0]['change_start']=='2010-11' and rows[0]['shares_changed'] is None
    checks={v.criterion:v.status for v in await q.preparation_check()}
    assert checks['coverage']=='pass' and checks['fields']==checks['quality']=='fail'
    assert await store.client.xlen(store.stream)==0


async def test_explicit_single_month_never_certifies_entire_default_history(monthly,monkeypatch):
    _,c,q,_=monthly
    monkeypatch.setattr('empire.features.performance.query.monthly_plan',
        lambda latest:[PERIOD] if latest==PERIOD else [PERIOD,'2025-09-01'])
    await c.execute(fresh=True,baseline_revision=await c.checkpoint_revision(),start_month=PERIOD,end_month=PERIOD)
    assert next(v for v in await q.preparation_check({'start':PERIOD,'end':PERIOD}) if v.criterion=='coverage').status=='pass'
    assert next(v for v in await q.preparation_check() if v.criterion=='coverage').status=='fail'
