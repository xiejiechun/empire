"""Source → Redis → unified archive → typed query in UUID-owned SQL/Redis."""
import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.collector import CollectionSourceGap
from empire.contracts.data import make_envelope
from empire.contracts.holders import KINDS, report_key
from empire.core.config import load_config
from empire.plugins.collectors.ths_holders_source import parse
from tests.prefetch_source import prefetch_http
from tests.test_ths_holders import STOCK, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to private SQL/Redis')]


@pytest.fixture(params=list(KINDS))
async def holders(request):
    kind = request.param
    cfg = copy.deepcopy(load_config())
    m, store, feed = build_manager(cfg), None, {'name': '股东', 'bond': True}
    try:
        await m.start('collector.ths_holders')
        c, q, store = m.registry.get('collector.ths_holders'), m.registry.get(kind + '.query'), m.registry.get('redis.store')
        c.query.securities = AsyncMock(return_value=[STOCK])
        with q.mysql.engine.begin() as conn:
            conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:code,:name)'),
                         dict(code=STOCK['unified_code'], name=STOCK['name']))
        c.session = type('Session', (), {'headers': lambda *a: {}})()
        c.http = prefetch_http(request=AsyncMock(side_effect=lambda method, url, **kw:
            httpx.Response(200, content=source(code='000000' if url.split('/')[-2] in feed.get('bad_codes', set()) else url.split('/')[-2], name=feed['name'], bond=feed['bond'],
                count=9 if url.split('/')[-2] in feed.get('bad_codes', set()) else 10,
                exit_order=feed.get('exit_order', False), tied=feed.get('tied', False),
                expanded=feed.get('expanded', False)).encode('gb18030'))))
        yield m, c, q, store, feed
    finally:
        await m.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                await client.delete(*keys)
            await client.aclose()


async def collect(c):
    return await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision()), 20)


async def dashboard(q, request):
    from types import SimpleNamespace

    from empire.plugins.data.preparation import PreparationPlugin
    preparation = PreparationPlugin(q.preparation)
    await preparation.start(SimpleNamespace(optional=lambda cap: q if cap == q.kind + '.query' else None))
    return next(r for r in (await preparation.report(request))['rows'] if r['id'] == q.kind)


@pytest.mark.parametrize('shape', ['missing_ratio', 'quantity_mismatch', 'ratio_mismatch',
                                  'missing_quantity_summary', 'missing_ratio_summary', 'missing_quantity', 'missing_exit_quantity', 'future_date'])
async def test_source_quality_roundtrip_hot_cold_recovery_and_old_version(holders, shape):
    from tests.test_holder_quality import quality_source
    m, c, q, store, feed = holders
    body = quality_source(q.kind, shape)
    c.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, content=body.encode('gb18030'))))
    await collect(c)
    expected = parse(body, q.kind, STOCK)[0]
    key = report_key(expected)
    assert await q.detail(key) == expected
    assert (await q.browse(code=STOCK['code']))['rows'][0]['quality_flags'] == expected['quality_flags']
    checks = await q.preparation_check(dict(codes=[STOCK['code']], purpose='analysis'))
    assert next(x for x in checks if x.criterion == 'coverage').status == 'pass'
    quality = next(x for x in checks if x.criterion == 'quality')
    assert quality.status == 'fail' and not quality.blocking
    # Exercise the actual dashboard aggregation, not only the query contribution.
    row = await dashboard(q, dict(codes=[STOCK['code']], purpose='analysis'))
    assert row['assessment']['integrity'] == '通过' and row['assessment']['quality'] == '有限制'
    assert row['assessment']['use_state'] == '可用（有限制）'
    historical = await dashboard(q, dict(codes=[STOCK['code']], purpose='historical_signal'))
    assert historical['assessment']['integrity'] == '通过'
    assert historical['assessment']['quality'] == '有异常' and not historical['assessment']['usable']
    archive = m.registry.get('archive.worker')
    writes = []
    def capture(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and any(t in sql for t in ('holder_report', 'holder_member')):
            writes.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    try:
        await collect(c)
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
        await collect(c)
        assert not writes and await store.client.xlen(store.stream) == 0
        # The same source identity can recover; the quality marker must clear.
        c.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, content=source().encode('gb18030'))))
        await collect(c)
        assert writes
        if shape != 'future_date':
            assert (await q.detail(key))['quality_flags'] == 0
        before = len(writes)
        rows = {kind: parse(body, kind, STOCK) for kind in KINDS}
        e = make_envelope(source='ths', dataset='holders.reports', schema_version=5, job_key=c.job_key,
            batch_id=uuid4().hex, run_id=uuid4().hex, business_key=STOCK['unified_code'],
            payload=dict(page=1, unit=STOCK['unified_code'], reports=rows, manifest=None, gaps=[])).model_copy(
                update={'observed_at': datetime.now(UTC) - timedelta(hours=1)})
        state = await c.ingest.checkpoint(c.job_key)
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
        await c.ingest.publish_page([e], job_key=c.job_key, expected_revision=state['revision'], cursor=state['cursor'])
        await archive.flush()
        assert len(writes) == before and await store.client.xlen(store.stream) == 0
        assert (await q.detail(key))['quality_flags'] == (128 if shape == 'future_date' else 0)
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


@pytest.mark.parametrize('shape', ['large_notice', 'periodic84', 'missing_sections'])
async def test_large_notice_unknown_exit_ratios_and_parallel_bond_ranks_roundtrip(holders, shape):
    from tests.test_holder_error_shapes import large_notice
    m, c, q, store, feed = holders
    body = large_notice().replace('<td>2</td><td>股东1', '<td>1</td><td>股东1')
    if shape == 'periodic84':
        body = source(count=84)
        start = body.index('<div id="bondholder">')
        body = body[:start].replace('100.00万股', '840.00万股').replace('<em>10.00%</em>', '<em>84.00%</em>') + source()[source().index('<div id="bondholder">'):]
    elif shape == 'missing_sections':
        body = body[:body.index('<div id="flowholder">')] + '<div id="holdernum"></div><div id="holdlevel"></div></html>'
    c.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, content=body.encode('gb18030'))))
    await collect(c)
    expected = parse(body, q.kind, STOCK)
    for row in expected:
        assert await q.detail(report_key(row)) == row
    assert len((await q.browse(code=STOCK['code']))['rows']) == len(expected)
    archive = m.registry.get('archive.worker')
    writes = []
    def capture(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and any(t in sql for t in ('holder_report', 'holder_member')):
            writes.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    try:
        await collect(c)  # trusted digest
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
        await collect(c)  # cold SQL comparison
        assert not writes
        assert await store.client.xlen(store.stream) == 0
        for row in expected:
            assert await q.detail(report_key(row)) == row
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


@pytest.mark.parametrize('failure', ['identity', 'empty_bond'])
async def test_source_gap_archives_later_security_without_complete_proof_then_recovers(holders, failure):
    from empire.contracts.preparation_scope import PreparationScope
    m, c, q, store, feed = holders
    second = {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}
    c.query.securities.return_value = [STOCK, second]
    with q.mysql.engine.begin() as conn:
        conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:code,:name)'),
                     dict(code=second['unified_code'], name='后续证券'))
    feed['bad_codes'] = {STOCK['code']}
    if failure == 'empty_bond':
        def response(method, url, **kwargs):
            body = source(code=url.split('/')[-2])
            if url.split('/')[-2] in feed['bad_codes']:
                body = body.replace('<span>燃23转债</span>', '<span></span>')
            return httpx.Response(200, content=body.encode('gb18030'))
        c.http = prefetch_http(request=AsyncMock(side_effect=response))
    outcome = CollectionSourceGap if failure == 'empty_bond' else ValueError
    message = '可识别报告已确认归档' if failure == 'empty_bond' else '1只证券来源校验失败'
    with pytest.raises(outcome, match=message):
        await collect(c)
    expected = parse(source(code=second['code']), q.kind, second)[0]
    assert await q.detail(report_key(expected)) == expected
    assert await store.client.xlen(store.stream) == 0
    cursor = (await c.ingest.checkpoint(c.job_key))['cursor']
    assert cursor['index'] == 0 and cursor['collected'] == 0 and cursor['phase'] == 'fetch'
    audit = await q.mysql.read(q.audit, PreparationScope(codes=(STOCK['code'], second['code'])))
    missing = failure == 'identity' or q.kind == 'bond_holders'
    assert audit['complete'] == (not missing) and audit['missing'] == int(missing)
    assert audit['reports'] == (1 if failure == 'identity' or q.kind == 'bond_holders' else 2)
    checks = await q.preparation_check(dict(codes=[second['code']], purpose='analysis'))
    assert all(x.status == 'pass' for x in checks if x.criterion in ('fields', 'keys', 'coverage', 'freshness'))
    failed = await q.preparation_check(dict(codes=[STOCK['code']], purpose='analysis'))
    coverage = next(x for x in failed if x.criterion == 'coverage')
    if missing:
        assert coverage.findings[0]['security'] == STOCK['unified_code']
    else:
        assert coverage.status == 'pass'
    unknown = await q.preparation_check(dict(codes=['999999'], purpose='analysis'))
    assert next(x for x in unknown if x.criterion == 'coverage').status == 'fail'
    feed['bad_codes'] = set()
    await collect(c)
    for stock in (STOCK, second):
        expected = parse(source(code=stock['code']), q.kind, stock)[0]
        assert await q.detail(report_key(expected)) == expected
    assert await store.client.xlen(store.stream) == 0
    audit = await q.mysql.read(q.audit, PreparationScope(codes=(STOCK['code'], second['code'])))
    assert audit['complete']


async def test_pending_holder_upgrade_atomic_compare_and_safe_replay(holders):
    from scripts.holder_pending_schema import REPLACE, convert
    m, c, q, store, feed = holders
    archive = m.registry.get('archive.worker')
    reports = {kind: parse(source(), kind, STOCK) for kind in KINDS}
    old = make_envelope(source='ths', dataset='holders.reports', schema_version=4,
        business_key=STOCK['unified_code'], job_key=c.job_key, run_id=uuid4().hex,
        batch_id=uuid4().hex, payload=dict(page=1, unit=STOCK['unified_code'], reports=reports, manifest=None))
    raw = old.model_dump_json()
    async with archive.lock:
        ident = await store.client.xadd(store.stream, {'envelope': raw})
        with pytest.raises(Exception, match='changed'):
            await store.client.eval(REPLACE, 1, store.stream, ident, 'different', convert(raw).model_dump_json())
        assert (await store.client.xrange(store.stream))[0][1]['envelope'] == raw
        new_id = await store.client.eval(REPLACE, 1, store.stream, ident, raw, convert(raw).model_dump_json())
        assert await store.client.xlen(store.stream) == 1
        assert (await store.client.xrange(store.stream))[0][0] == new_id
        with pytest.raises(Exception, match='missing'):
            await store.client.eval(REPLACE, 1, store.stream, ident, raw, convert(raw).model_dump_json())
    archive = m.registry.get('archive.worker')
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    assert await q.detail(report_key(reports[q.kind][0])) == reports[q.kind][0]


async def test_partial_bond_gap_roundtrip_duplicate_recovery_and_late_replay(holders):
    from tests.test_holder_identity_gaps import mixed_bonds
    m, c, q, store, feed = holders
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, content=mixed_bonds().encode('gb18030'))
    observed = datetime.now(UTC) - timedelta(seconds=1)
    gaps = []
    reports = {kind: parse(mixed_bonds(), kind, STOCK, gaps=gaps) for kind in KINDS}
    for attempt in range(2):
        writes = []
        def capture(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith(('INSERT INTO HOLDER_', 'UPDATE HOLDER_', 'DELETE FROM HOLDER_')):
                writes.append(statement)
        event.listen(q.mysql.engine, 'before_cursor_execute', capture)
        try:
            with pytest.raises(CollectionSourceGap, match='可识别报告已确认归档'):
                await collect(c)
        finally:
            event.remove(q.mysql.engine, 'before_cursor_execute', capture)
        if attempt:
            assert not writes
        for row in reports[q.kind]:
            assert await q.detail(report_key(row)) == row
        check = next(e for e in await q.preparation_check(dict(codes=[STOCK['code']])) if e.criterion == 'coverage')
        assert check.status == ('fail' if q.kind == 'bond_holders' else 'pass')
        if q.kind == 'bond_holders':
            assert '2026-06-30' in check.findings[0]['message']
        assert await store.client.xlen(store.stream) == 0
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, content=source().encode('gb18030'))
    await collect(c)
    old = make_envelope(source='ths', dataset='holders.reports', schema_version=5, job_key=c.job_key,
        business_key=STOCK['unified_code'], batch_id=uuid4().hex, run_id=uuid4().hex,
        payload=dict(page=1, unit=STOCK['unified_code'], reports=reports, manifest=None, gaps=gaps)).model_copy(
            update={'observed_at': observed})
    state = await c.ingest.checkpoint(c.job_key)
    await c.ingest.publish_page([old], job_key=c.job_key, expected_revision=state['revision'], cursor=state['cursor'])
    await m.registry.get('archive.worker').flush()
    assert await store.client.xlen(store.stream) == 0
    check = next(e for e in await q.preparation_check(dict(codes=[STOCK['code']])) if e.criterion == 'coverage')
    assert check.status == 'pass'


async def test_future_source_flag_recovers_only_on_new_observation_and_old_replay_clears(holders):
    from empire.core.time import CHINA
    m, c, q, store, feed = holders
    archive = m.registry.get('archive.worker')
    now = datetime.now(UTC)
    body = source().replace('2026-06-30', now.astimezone(CHINA).date().isoformat())
    async def publish(observed):
        sections = {k: parse(body, k, STOCK, today=observed.astimezone(CHINA).date()) for k in KINDS}
        e = make_envelope(source='ths', dataset='holders.reports', schema_version=5, job_key=c.job_key,
            business_key=STOCK['unified_code'], run_id=uuid4().hex, batch_id=uuid4().hex,
            payload=dict(page=1, unit=STOCK['unified_code'], reports=sections, manifest=None, gaps=[])).model_copy(
                update={'observed_at': observed})
        state = await c.ingest.checkpoint(c.job_key)
        await c.ingest.publish_page([e], job_key=c.job_key, expected_revision=state['revision'], cursor=state['cursor'])
        await archive.flush()
        assert await store.client.xlen(store.stream) == 0
        return sections[q.kind][0]
    old = await publish(now - timedelta(days=1))
    key = report_key(old)
    assert (await q.detail(key))['quality_flags'] == 128
    new = await publish(now)
    assert new['quality_flags'] == 0 and await q.detail(key) == new
    await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
    await publish(now - timedelta(days=1))
    assert await q.detail(key) == new


@pytest.mark.parametrize('expansion', ['tied', 'expanded'])
async def test_expanded_source_to_query_hot_cold_and_successful_cleanup(holders, expansion):
    m, c, q, store, feed = holders
    feed[expansion] = True
    await collect(c)
    expected = parse(source(**{expansion: True}), q.kind, STOCK)[0]
    assert await q.detail(report_key(expected)) == expected
    assert await store.client.xlen(store.stream) == 0
    await collect(c)
    assert await q.detail(report_key(expected)) == expected
    assert await store.client.xlen(store.stream) == 0
    await m.registry.get('archive.worker').fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
    await collect(c)
    assert await q.detail(report_key(expected)) == expected
    assert await store.client.xlen(store.stream) == 0


async def test_hot_cold_revision_old_observation_and_field_repair(holders, monkeypatch):
    m, c, q, store, feed = holders
    archive = m.registry.get('archive.worker')
    await collect(c)
    key = report_key(parse(source(), q.kind, STOCK)[0])
    detail = await q.detail(key)
    assert detail == parse(source(), q.kind, STOCK)[0]
    assert (await q.browse(code='601139'))['rows'][0]['member_count'] == 10
    assert (await q.preparation_check())[2].status == 'pass'
    calls, dml = [], []
    original = q.mysql.archive
    async def counted(records):
        calls.append(1)
        return await original(records)
    def capture(conn, cursor, sql, parameters, context, many):
        if any(t in sql for t in ('holder_report', 'holder_member')) and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            dml.append(sql)
    monkeypatch.setattr(q.mysql, 'archive', counted)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    try:
        await collect(c)
        assert not calls and not dml and await store.client.xlen(store.stream) == 0
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
        await collect(c)
        assert calls and not dml
        if q.kind == 'bond_holders':
            feed['exit_order'] = True
            await collect(c)
            assert [r['source_rank'] for r in (await q.detail(key))['members'] if r['member_group'] == 'exited'] == [4, 2]
        feed['name'] = '修订持有人'
        await collect(c)
        assert dml and (await q.detail(key))['members'][0]['holder_name'] == '修订持有人0'
        # Damage exactly this private source report, invalidating its source cache first.
        async with archive.lock:
            await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
            with q.mysql.engine.begin() as conn:
                conn.execute(text("UPDATE holder_member SET holder_name='同数异集' WHERE report_key=:key AND member_group='current' AND seq=1"), {'key': key})
        assert (await q.preparation_check())[2].status == 'fail'
        await collect(c)
        assert (await q.detail(key))['members'][0]['holder_name'] == '修订持有人0'
        async with archive.lock:
            await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
            with q.mysql.engine.begin() as conn:
                conn.execute(text('UPDATE holder_report SET member_count=9 WHERE report_key=:key'), {'key': key})
        assert (await q.preparation_check())[2].status == 'fail'
        await collect(c)
        assert (await q.browse(code='601139'))['rows'][0]['member_count'] == 10
        before = len(dml)
        reports = {kind: parse(source(), kind, STOCK) for kind in KINDS}
        batch = uuid4().hex
        envelope = make_envelope(source='ths', dataset='holders.reports', schema_version=5, job_key=c.job_key,
            batch_id=batch, run_id=batch, business_key=STOCK['unified_code'],
            payload=dict(page=1, unit=STOCK['unified_code'], reports=reports, manifest=None, gaps=[])).model_copy(
                update={'observed_at': datetime.now(UTC) - timedelta(hours=1)})
        state = await c.ingest.checkpoint(c.job_key)
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
        await c.ingest.publish_page([envelope], job_key=c.job_key, expected_revision=state['revision'], cursor=state['cursor'])
        await archive.flush()
        assert len(dml) == before and await store.client.xlen(store.stream) == 0
        assert (await q.detail(key))['members'][0]['holder_name'] == '修订持有人0'
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


async def test_sql_commit_ack_failure_replay_and_checkpoint_loss(holders, monkeypatch):
    m, c, q, store, feed = holders
    archive = m.registry.get('archive.worker')
    acknowledge = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('holder test ack interruption')))
    task = asyncio.create_task(collect(c))
    key = report_key(parse(source(), q.kind, STOCK)[0])
    try:
        async with asyncio.timeout(5):
            while not (await q.detail(key)) or not await store.client.xlen(store.stream):
                await asyncio.sleep(.03)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        calls = c.http.request.await_count
        monkeypatch.setattr(archive, 'acknowledge', acknowledge)
        archive.request_flush()
        await collect(c)
        assert c.http.request.await_count == calls and await store.client.xlen(store.stream) == 0
        await store.client.delete(c.ingest._checkpoint_key(c.job_key))
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
        await collect(c)
        assert c.http.request.await_count == calls + 1 and (await q.preparation_check())[2].status == 'pass'
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_failed_sql_retains_queue_and_next_security_does_not_wait(holders, monkeypatch):
    m, c, q, store, feed = holders
    stocks = [STOCK, {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}]
    c.query.securities.return_value = stocks
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200, content=source(code=url.split('/')[-2]).encode('gb18030'))
    original, gate = q.mysql.archive, asyncio.Event()
    failed = asyncio.Event()
    async def delayed(records):
        await gate.wait()
        if not failed.is_set():
            failed.set()
            raise RuntimeError('isolated holder SQL failure before commit')
        return await original(records)
    monkeypatch.setattr(q.mysql, 'archive', delayed)
    task = asyncio.create_task(collect(c))
    try:
        async with asyncio.timeout(5):
            while (await c.ingest.checkpoint(c.job_key))['cursor'].get('phase') != 'awaiting_archive':
                await asyncio.sleep(.01)
        assert c.http.request.await_count == 2 and await store.client.xlen(store.stream) >= 2
        gate.set()
        await asyncio.wait_for(failed.wait(), 5)
        assert await store.client.xlen(store.stream) >= 2
        m.registry.get('archive.worker').request_flush()
        await task
        assert await store.client.xlen(store.stream) == 0
    finally:
        gate.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_later_section_sql_failure_rolls_back_all_three(holders, monkeypatch):
    m, c, q, store, feed = holders
    archive = m.registry.get('archive.worker')
    writes = []
    failed = asyncio.Event()
    loop = asyncio.get_running_loop()
    def interrupt(conn, cursor, sql, params, context, many):
        if sql.startswith('INSERT INTO holder_report'):
            writes.append(1)
            if len(writes) == 2:
                loop.call_soon_threadsafe(failed.set)
                raise RuntimeError('isolated second-section transaction failure')
    original = q.mysql.archive
    replay = asyncio.Event()
    async def bounded(records):
        if failed.is_set():
            await replay.wait()
        return await original(records)
    monkeypatch.setattr(q.mysql, 'archive', bounded)
    event.listen(q.mysql.engine, 'before_cursor_execute', interrupt)
    task = asyncio.create_task(collect(c))
    try:
        await asyncio.wait_for(failed.wait(), 5)
        async with asyncio.timeout(5):
            while archive.health().get('status') != 'degraded':
                await asyncio.sleep(.02)
        with q.mysql.read_engine.connect() as conn:
            assert conn.execute(text('SELECT COUNT(*) FROM holder_report')).scalar_one() == 0
            assert conn.execute(text('SELECT COUNT(*) FROM holder_member')).scalar_one() == 0
        assert await store.client.xlen(store.stream) > 0
        event.remove(q.mysql.engine, 'before_cursor_execute', interrupt)
        replay.set()
        archive.request_flush()
        await task
        assert c.http.request.await_count == 1 and await store.client.xlen(store.stream) == 0
        for kind in KINDS:
            query = m.registry.get(kind + '.query')
            assert (await query.preparation_check())[2].status == 'pass'
    finally:
        if event.contains(q.mysql.engine, 'before_cursor_execute', interrupt):
            event.remove(q.mysql.engine, 'before_cursor_execute', interrupt)
        replay.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

async def test_selected_unit_proof_and_optional_cache_freshness(holders):
    from empire.plugins.infra.collection_state import read_state, save_state
    m, c, q, store, feed = holders
    await collect(c)
    archive = m.registry.get('archive.worker')
    cache = archive.fingerprints
    security = STOCK['unified_code']
    cached = (await cache.peek(q.mapping.FINGERPRINT_NAMESPACE, 'ths', [security]))[security]
    healthy = await dashboard(q, dict(codes=[STOCK['code']], purpose='analysis'))
    assert healthy['assessment']['quality'] == '通过'
    assert healthy['assessment']['use_state'] == '可用（有限制）'
    async with archive.lock:
        with q.mysql.engine.begin() as conn:
            original = read_state(conn, q.namespace, 'ths-holders', 'ths')
            state = copy.deepcopy(original)
            state['manifest'] = {'securities': ['999999.SH'], 'observed_at': 'invalid'}
            stale = (datetime.now(UTC) - timedelta(days=4)).isoformat(timespec='microseconds')
            state['units'][security]['observed_at'] = stale
            for proof in state['units'][security]['kinds'].values():
                proof['observed_at'] = stale
            save_state(conn, q.namespace, 'ths-holders', 'ths', 'holders.reports', state, original)
    async def status(criterion):
        return next(x for x in await q.preparation_check(dict(codes=[STOCK['code']], purpose='analysis')) if x.criterion == criterion)
    # An unrelated invalid global manifest cannot block this independently proved issuer.
    assert (await status('coverage')).status == 'pass'
    assert (await status('freshness')).status == 'pass'  # Matching three-column canonical cache.
    await cache.put(q.mapping.FINGERPRINT_NAMESPACE, 'ths', {security: {**cached, 'hash': 'f' * 64}})
    assert (await status('freshness')).status == 'fail'
    await cache.invalidate_entries(q.mapping.FINGERPRINT_NAMESPACE, 'ths', [security])
    assert (await status('coverage')).status == 'pass'
    assert (await status('freshness')).status == 'fail'
    # Same count with a different identity set must fail, including explicitly empty columns.
    async with archive.lock:
        with q.mysql.engine.begin() as conn:
            bad = copy.deepcopy(state)
            proof = bad['units'][security]['kinds'][q.kind]
            proof['report_keys'] = ['0' * 64] * proof['count']
            save_state(conn, q.namespace, 'ths-holders', 'ths', 'holders.reports', bad, state)
    assert (await status('coverage')).status == 'fail'
    async with archive.lock:
        with q.mysql.engine.begin() as conn:
            future = copy.deepcopy(state)
            future['units'][security]['kinds'][q.kind]['observed_at'] = (datetime.now(UTC) + timedelta(days=1)).isoformat(timespec='microseconds')
            save_state(conn, q.namespace, 'ths-holders', 'ths', 'holders.reports', future, bad)
    assert (await status('coverage')).status == 'fail'

async def test_concurrent_revision_cannot_lend_freshness_to_old_audit(holders, monkeypatch):
    from empire.plugins.infra.collection_state import read_state, save_state
    m, c, q, store, feed = holders
    await collect(c)
    archive = m.registry.get('archive.worker')
    security = STOCK['unified_code']
    async with archive.lock:
        with q.mysql.engine.begin() as conn:
            previous = read_state(conn, q.namespace, 'ths-holders', 'ths')
            stale = copy.deepcopy(previous)
            stamp = (datetime.now(UTC) - timedelta(days=4)).isoformat(timespec='microseconds')
            stale['units'][security]['observed_at'] = stamp
            for proof in stale['units'][security]['kinds'].values():
                proof['observed_at'] = stamp
            save_state(conn, q.namespace, 'ths-holders', 'ths', 'holders.reports', stale, previous)
    original_read = q.mysql.read
    revise = True
    async def read(operation, *args):
        nonlocal revise
        result = await original_read(operation, *args)
        if operation == q.audit and revise:
            revise = False
            feed['name'] = '并发修订'
            await collect(c)  # Actual SQL and canonical Redis fingerprint change after the audit snapshot.
        return result
    monkeypatch.setattr(q.mysql, 'read', read)
    checks = await q.preparation_check(dict(codes=[STOCK['code']], purpose='analysis'))
    assert next(x for x in checks if x.criterion == 'coverage').status == 'pass'
    assert next(x for x in checks if x.criterion == 'freshness').status == 'fail'
    key = report_key(parse(source(), q.kind, STOCK)[0])
    assert (await q.detail(key))['members'][0]['holder_name'] == '并发修订0'
    current = await q.preparation_check(dict(codes=[STOCK['code']], purpose='analysis'))
    assert next(x for x in current if x.criterion == 'freshness').status == 'pass'

async def test_multiple_issuers_use_their_own_matching_hot_confirmations(holders):
    from empire.plugins.infra.collection_state import read_state, save_state
    m, c, q, store, feed = holders
    second = {**STOCK, 'code': '601140', 'unified_code': '601140.SH'}
    c.query.securities.return_value = [STOCK, second]
    with q.mysql.engine.begin() as conn:
        conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:code,:name)'),
                     dict(code=second['unified_code'], name='另一证券'))
    await collect(c)
    async with m.registry.get('archive.worker').lock:
        with q.mysql.engine.begin() as conn:
            previous = read_state(conn, q.namespace, 'ths-holders', 'ths')
            stale = copy.deepcopy(previous)
            stamp = (datetime.now(UTC) - timedelta(days=4)).isoformat(timespec='microseconds')
            for unit in stale['units'].values():
                unit['observed_at'] = stamp
                for proof in unit['kinds'].values():
                    proof['observed_at'] = stamp
            save_state(conn, q.namespace, 'ths-holders', 'ths', 'holders.reports', stale, previous)
    checks = await q.preparation_check(dict(codes=[STOCK['code'], second['code']], purpose='analysis'))
    assert next(x for x in checks if x.criterion == 'coverage').status == 'pass'
    assert next(x for x in checks if x.criterion == 'freshness').status == 'pass'
