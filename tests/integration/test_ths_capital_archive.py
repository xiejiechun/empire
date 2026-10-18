"""All typed sections through the real Redis/SQL archive, in private schemas."""
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
from empire.contracts.capital_transport import SCHEMA, pack
from empire.contracts.data import make_envelope
from empire.contracts.preparation_scope import PreparationScope
from empire.contracts.ths_capital import DATASET, JOB, PROJECT, TABLES
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.plugins.collectors.ths_capital_source import parse
from empire.plugins.datasets.ths_capital import read_window
from tests.prefetch_source import prefetch_http
from tests.test_ths_capital import STOCK, source

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Opt in to private SQL/Redis')]


@pytest.fixture
async def capital():
    cfg = copy.deepcopy(load_config())
    m, store, feed = build_manager(cfg), None, dict(text=source())
    try:
        await m.start('collector.ths_capital')
        c, q, store = m.registry.get('collector.ths_capital'), m.registry.get('ths_capital.query'), m.registry.get('redis.store')
        c.query.securities = AsyncMock(return_value=[STOCK])
        with q.mysql.engine.begin() as conn:
            conn.execute(text('INSERT INTO stock(unified_code,name) VALUES(:code,:name)'), dict(code=STOCK['unified_code'], name=STOCK['name']))
        c.session = type('Session', (), {'headers': lambda *a: {}})()
        c.http = prefetch_http(request=AsyncMock(side_effect=lambda *a, **kw: httpx.Response(200, content=feed['text'].encode('gb18030'))))
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


@pytest.mark.parametrize('foreign_value,amount,currency', [
    ('6.00万亿越南盾', '6000000000000', '越南盾'),
    ('5.54亿泰铢', '554000000', '泰铢'),
    ('150.00万文莱林吉特', '1500000', '文莱林吉特'),
])
async def test_roundtrip_hot_cold_zero_dml_revision_old_replay_and_required_field_repair(
        capital, monkeypatch, foreign_value, amount, currency):
    m, c, q, store, feed = capital
    feed['text'] = feed['text'].replace('-0.32', '-0.00').replace('未公布%', '--%').replace('500万美元', '31.08亿挪威克朗')
    feed['text'] = feed['text'].replace('30万股', '--').replace('100万股', '--').replace('标的一', '未公布')
    feed['text'] = feed['text'].replace('5500.00万澳大利亚元', foreign_value)
    feed['text'] = feed['text'].replace('参股企业', '--')
    future = (datetime.now(CHINA) + timedelta(days=1)).date().isoformat()
    feed['text'] = feed['text'].replace('2025-01-01', future)
    await collect(c)
    expected = parse(feed['text'].encode('gb18030'), STOCK, datetime.now(CHINA).date())
    assert expected['rows']['capital_ipo'][0]['eps'] == '0'
    assert expected['rows']['capital_ipo'][0]['target'] is None
    assert expected['rows']['capital_encumbrance'][0]['quantity'] is None
    from empire.contracts.ths_capital import FUTURE_ANNOUNCEMENT
    assert expected['rows']['capital_funding'][0]['event_date'] == future
    assert expected['availability']['raise_'] == FUTURE_ANNOUNCEMENT
    assert any(r['target'] is None and r['profit'] == '-10000'
               for r in expected['rows']['capital_equity_position'])
    assert any(r['quantity'] is None and r['actual_date'] == '2025-02-28'
               for r in expected['rows']['capital_release'])
    acquisition = next(r for r in expected['rows']['capital_transaction'] if r['section'] == 'asset')
    assert acquisition['amount'] == '3108000000' and acquisition['currency'] == '挪威克朗'
    related = next(r for r in expected['rows']['capital_transaction'] if r['section'] == 'connect')
    assert related['amount'] == amount and related['currency'] == currency
    assert any(r['target'] == '标的二' and r['ratio'] is None
               for r in expected['rows']['capital_equity_position'])
    with q.mysql.read_engine.begin() as conn:
        assert read_window(conn, STOCK['unified_code']) == expected['rows']
    for table, rows in expected['rows'].items():
        for row in rows:
            detail = await q.detail(table, row['record_key'])
            assert {k: detail[k] for k in row} == row
    assert (await q.mysql.read(q.audit, PreparationScope(codes=('601139',))))['complete']
    archive = m.registry.get('archive.worker')
    statements = []
    def capture(conn, cursor, sql, parameters, context, many):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and any(t in sql for t in TABLES):
            statements.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', capture)
    try:
        async def forbidden_sql(*a, **kw):
            raise AssertionError('trusted fingerprint must not access MySQL archive')
        with monkeypatch.context() as hot:
            hot.setattr(q.mysql, 'archive', forbidden_sql)
            await collect(c)
        assert not statements and await store.client.xlen(store.stream) == 0
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
        await collect(c)
        assert not statements and await store.client.xlen(store.stream) == 0
        feed['text'] = feed['text'].replace('完整转让详情', '修订后的完整转让详情')
        await collect(c)
        assert statements
        before = len(statements)
        old = make_envelope(source='ths', dataset=DATASET, schema_version=SCHEMA, job_key=JOB,
            batch_id=uuid4().hex, run_id=uuid4().hex, business_key=STOCK['unified_code'],
            payload=dict(page=1, unit=STOCK['unified_code'], **{**expected, 'rows': pack(expected['rows'])}, manifest=None)).model_copy(
                update=dict(observed_at=datetime.now(UTC) - timedelta(hours=1)))
        state = await c.ingest.checkpoint(JOB)
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
        await c.ingest.publish_page([old], job_key=JOB, expected_revision=state['revision'], cursor=state['cursor'])
        await archive.flush()
        assert len(statements) == before and await store.client.xlen(store.stream) == 0
        # Explicitly emulate a missing required association in test-owned SQL.
        with q.mysql.engine.begin() as conn:
            conn.execute(text('DELETE FROM capital_release LIMIT 1'))
        assert not (await q.mysql.read(q.audit, PreparationScope(codes=('601139',))))['complete']
        assert not (await q.mysql.read(q.audit, PreparationScope(codes=('601139',)), 'pledge'))['complete']
        assert (await q.mysql.read(q.audit, PreparationScope(codes=('601139',)), 'raise_'))['complete']
        await archive.fingerprints.invalidate(q.mapping.FINGERPRINT_NAMESPACE, 'ths')
        await collect(c)
        assert (await q.mysql.read(q.audit, PreparationScope(codes=('601139',))))['complete']
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', capture)


async def test_same_count_different_set_preserves_history_and_keyset_pages(capital):
    m, c, q, store, feed = capital
    await collect(c)
    before = await q.browse('capital_transaction', 'transfer')
    removed = next(r for r in before['rows'] if r['target'] == '目标二')
    feed['text'] = feed['text'].replace('目标二', '新标的')
    await collect(c)
    assert (await q.detail('capital_transaction', removed['record_key']))['in_window'] is False
    expected = parse(feed['text'].encode('gb18030'), STOCK)
    with q.mysql.read_engine.begin() as conn:
        assert read_window(conn, STOCK['unified_code']) == expected['rows']
    assert (await q.mysql.read(q.audit, PreparationScope(codes=('601139',))))['complete']
    after, values = None, []
    while True:
        page = await q.browse('capital_transaction', 'transfer', after=after, limit=1)
        values.extend(page['rows'])
        if not page['next']:
            break
        after = page['next']
    assert len(values) == 3 and len({r['record_key'] for r in values}) == 3
    assert {r['target'] for r in values} == {'目标二', '目标三', '新标的'}
    assert (await q.browse('capital_ipo', 'ipo', limit=1))['rows'][0]['event_date'] is None
    await collect(c)
    assert await store.client.xlen(store.stream) == 0


async def test_failure_keeps_queue_sql_commit_then_redis_failure_replays_safely(capital, monkeypatch):
    m, c, q, store, feed = capital
    archive = m.registry.get('archive.worker')
    await archive.stop()
    archive.stop_event.clear()
    task = asyncio.create_task(collect(c))
    async with asyncio.timeout(5):
        while await store.client.xlen(store.stream) != 2:
            await asyncio.sleep(.01)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    # Find the actual catalogue mapping, independent of query plugin lifetime.
    catalog = m.registry.get('dataset.catalog')
    actual = next(d.mapping for d in catalog.contributions if DATASET in d.mapping.DATASETS)
    original = actual.write
    def failed(*a):
        raise RuntimeError('injected SQL failure')
    monkeypatch.setattr(actual, 'write', failed)
    with pytest.raises(RuntimeError, match='injected SQL'):
        await archive.flush()
    assert await store.client.xlen(store.stream) == 2
    monkeypatch.setattr(actual, 'write', original)
    confirmation = archive.fingerprints.put
    async def failed_after_sql(*a, **kw):
        raise RuntimeError('injected post-commit Redis failure')
    monkeypatch.setattr(archive.fingerprints, 'put', failed_after_sql)
    with pytest.raises(RuntimeError, match='post-commit'):
        await archive.flush()
    assert await store.client.xlen(store.stream) >= 1
    with q.mysql.read_engine.begin() as conn:
        assert read_window(conn, STOCK['unified_code']) == parse(feed['text'].encode('gb18030'), STOCK)['rows']
    monkeypatch.setattr(archive.fingerprints, 'put', confirmation)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0
    assert PROJECT == q.mapping.PROJECT


async def test_large_security_atomic_archive_and_small_limit_retains_frontier(capital):
    m, c, q, store, feed = capital
    # A complete source with long but bounded independent descriptions exceeds
    # the old expanded JSON page, while the lossless wire fits the default cap.
    from tests.test_ths_capital import cells
    rows = ''.join(cells(['2025-01-01', f'大项目{i}', '1万', '0', '-', '-', '-',
                         '原始规范正文不可截断' * 1100]) for i in range(20))
    marker = '</tbody></table></div><div class="m_box" id="asset">'
    assert marker in feed['text']
    feed['text'] = feed['text'].replace(marker, rows + marker)
    expected = parse(feed['text'].encode('gb18030'), STOCK)
    import json
    assert len(json.dumps(expected, ensure_ascii=False).encode()) > 524288
    original_limit = c.ingest.settings.get('max_page_bytes', 524288)
    c.ingest.settings['max_page_bytes'] = 1024
    before = await c.ingest.checkpoint(JOB)
    with pytest.raises(ValueError, match='Page exceeds'):
        await collect(c)
    assert await c.ingest.checkpoint(JOB) == before
    assert await store.client.xlen(store.stream) == 0
    c.ingest.settings['max_page_bytes'] = original_limit
    await collect(c)
    with q.mysql.read_engine.begin() as conn:
        assert read_window(conn, STOCK['unified_code']) == expected['rows']
    assert c.stats['publication_bytes'] <= original_limit
    assert await store.client.xlen(store.stream) == 0
