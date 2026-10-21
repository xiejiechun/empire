"""Official-shaped bytes → decoder → Redis → unified archive → formal SQL query."""
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
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.features.trading_rules.contract import KINDS, SOURCE, citation_identity, digest
from tests.prefetch_source import prefetch_http
from tests.test_trading_rules import responses, sample

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to isolated integration')]


@pytest.fixture(params=KINDS)
async def rules(request):
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    manager = build_manager(cfg)
    c = manager.entries['collector.rules_' + request.param].plugin
    store = None
    try:
        await manager.start(c.manifest.id)
        q = manager.registry.get('rules.' + c.kind + '.query')
        store = manager.registry.get('redis.store')
        docs = responses()
        def respond(method, url, **kw):
            if url.startswith('https://www.bse.cn/'):
                assert 'User-Agent' not in kw['headers']  # Incomplete browser UA redirects the public API.
            return httpx.Response(200, content=docs[url])
        c.http = c.sources.http = prefetch_http(request=AsyncMock(side_effect=respond), response_policy=lambda _: None)
        yield manager, c, q, store
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            keys = [key async for key in client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(key.startswith(cfg['redis']['namespace'] + ':') for key in keys)
                await client.delete(*keys)
            await client.aclose()


async def collect(c):
    return await asyncio.wait_for(c.execute(baseline_revision=await c.checkpoint_revision()), 20)


async def test_seven_sources_to_formal_query_and_scope_limits(rules):
    _, c, q, store = rules
    result = await collect(c)
    values = (await q.list_rules())['rows']
    assert len(values) == result['collected'] == len(sample(c.kind)['rows'])
    from empire.features.trading_rules.dataset import canonical_payload
    expected = canonical_payload(c.kind, c.last_source)
    snapshot = await q.mysql.read(q.snapshot)
    assert values == expected['rows'] and snapshot[1] == expected['citations']
    first = await q.list_rules(limit=1)
    assert first['next']
    second = await q.list_rules(after=first['next'], limit=1)
    assert second['rows'][0]['record_key'] != first['rows'][0]['record_key']
    citation = await q.citation(first['rows'][0]['citation_key'])
    assert citation['excerpt'] and citation['source_url']
    assert await store.client.xlen(store.stream) == 0
    checks = {e.criterion: e.status for e in await q.preparation_check()}
    assert checks['keys'] == 'pass'
    assert (await q.preparation_check({'start': '2010-01-01'}))[2].status == 'fail'
    if c.kind not in ('stamp_duty', 'transfer_fee'):
        assert checks['coverage'] == 'pass'  # Current ordinary auction clauses include Beijing.
    if c.kind in ('settlement_rules', 'lot_rules', 'transfer_fee'):
        assert checks['quality'] == 'fail'
    elif c.kind in ('tick_rules', 'sessions', 'limit_rules'):
        assert (await q.preparation_check({'codes': ['600000'], 'start': '2026-07-06'}))[2].status == 'pass'


async def test_hot_cold_zero_dml_metadata_revision_late_old_and_corruption(rules, monkeypatch):
    manager, c, q, store = rules
    await collect(c)
    archive = manager.registry.get('archive.worker')
    calls, writes = [], []
    original = q.mysql.archive
    async def counted(records):
        calls.append(1)
        return await original(records)
    def capture(conn, cursor, sql, parameters, context, executemany):
        if 'trading_rule_' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    monkeypatch.setattr(q.mysql, 'archive', counted)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    try:
        await collect(c)
        assert not calls and not writes
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, SOURCE)
        await collect(c)
        assert calls and not writes
        original_payload = copy.deepcopy(c.last_source)
        revised = copy.deepcopy(original_payload)
        changed_ref = revised['citations'][0]
        old_ref = changed_ref['citation_key']
        changed_ref['document_hash'] = digest('reviewed metadata revision')
        changed_ref['citation_key'] = citation_identity(changed_ref)
        for row in revised['rows']:
            if row['citation_key'] == old_ref:
                row['citation_key'] = changed_ref['citation_key']
        c.sources.collect = AsyncMock(return_value=revised)
        await collect(c)
        current = (await q.list_rules())['rows']
        assert any(r['citation_key'] == changed_ref['citation_key'] for r in current)
        before = len(writes)
        batch = uuid4().hex
        old = make_envelope(source=SOURCE, dataset='rules.' + c.kind + '.complete', business_key=c.kind,
            job_key=c.job_key, run_id=batch, batch_id=batch, payload=original_payload).model_copy(update={'observed_at': datetime.now(UTC) - timedelta(hours=1)})
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, SOURCE)
        checkpoint = await c.ingest.checkpoint(c.job_key)
        await c.ingest.publish_page([old], job_key=c.job_key, expected_revision=checkpoint['revision'], cursor=checkpoint['cursor'])
        await archive.flush()
        assert len(writes) == before and (await q.list_rules())['rows'] == current
        async with archive.lock:
            await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, SOURCE)
            with q.mysql.engine.begin() as conn:
                conn.execute(text("UPDATE trading_rule_value SET market='XX' WHERE record_key=:key"), {'key': current[0]['record_key']})
                conn.execute(text("UPDATE trading_rule_citation SET excerpt='' WHERE citation_key=:key"), {'key': current[0]['citation_key']})
        assert (await q.preparation_check())[1].status == 'fail'
        await collect(c)
        assert (await q.preparation_check())[1].status == 'pass'
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


async def test_sql_commit_ack_failure_recovers_without_redownload(rules, monkeypatch):
    manager, c, q, store = rules
    archive = manager.registry.get('archive.worker')
    original = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ack interrupted')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        if (await q.list_rules())['rows'] and await store.client.xlen(store.stream):
            break
        await asyncio.sleep(.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert (await q.list_rules())['rows'] and await store.client.xlen(store.stream)
    calls = c.http.request.await_count
    monkeypatch.setattr(archive, 'acknowledge', original)
    archive.request_flush()
    await collect(c)
    assert c.http.request.await_count == calls and await store.client.xlen(store.stream) == 0


async def test_validation_and_transaction_failure_never_advance(rules, monkeypatch):
    manager, c, q, store = rules
    before = await c.ingest.checkpoint(c.job_key)
    docs = responses()
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200, content=b'<script>challenge</script>' if url.endswith(('.docx', '.pdf')) else docs[url])
    if c.kind in ('stamp_duty', 'transfer_fee'):
        c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, content=b'<html>not the source</html>')
    with pytest.raises(ValueError):
        await collect(c)
    assert await c.ingest.checkpoint(c.job_key) == before
    assert await store.client.xlen(store.stream) == 0
    c.http.request.side_effect = lambda method, url, **kw: httpx.Response(200, content=docs[url])
    monkeypatch.setattr(q.mysql, 'archive', AsyncMock(side_effect=RuntimeError('SQL transaction unavailable')))
    task = asyncio.create_task(collect(c))
    for _ in range(100):
        if await store.client.xlen(store.stream):
            break
        await asyncio.sleep(.01)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await store.client.xlen(store.stream) == 1 and not (await q.list_rules())['rows']
    assert (await c.ingest.checkpoint(c.job_key))['cursor']['phase'] == 'awaiting_archive'
