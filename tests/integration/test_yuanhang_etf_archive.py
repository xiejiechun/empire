"""ETF-specific formal Redis→archive→SQL→query and volatile-only boundaries."""
import asyncio
import copy
import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.core.config import load_config
from empire.desktop_bridge.preview import catalog as preview_catalog
from empire.desktop_bridge.preview import read as preview_read
from empire.features.yuanhang_etf import price_dataset
from empire.features.yuanhang_etf.contract import CATALOG_DATASET, PRICE_DATASET, PROJECTS, digest
from empire.plugins.infra.redis_store import create_client
from tests.test_yuanhang_etf import CATALOG, ROWS, latest_rows

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private SQL opt-in')]


def envelope(dataset=PRICE_DATASET, *, payload=None, observed=None):
    payload = payload or dict(code='511980.SH', native_market='USHJ', start='2026-01-01', through='2026-11-13',
        rows=ROWS, full=True, history_start=ROWS[0][0])
    result = make_envelope(source='ths_yuanhang', dataset=dataset,
        business_key='catalog' if dataset == CATALOG_DATASET else payload['code']+':2026',
        job_key=PROJECTS[dataset]+'-v1', batch_id=uuid4().hex, run_id='test', payload=dict(page=1, **payload))
    return result.model_copy(update={'observed_at': observed}) if observed else result


@pytest.fixture
async def etfs():
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:'+uuid4().hex
    manager, store = build_manager(cfg), None
    async def identity_start(context):
        return {'yuanhang.identity': SimpleNamespace()}
    manager.entries['source.yuanhang_identity'].plugin.start = identity_start
    try:
        for cap in ('collector.yuanhang_etfs', 'collector.yuanhang_etf_prices', 'collector.yuanhang_etf_latest'):
            await manager.start(cap)
        get = manager.registry.get
        catalog, prices, live = (get(c) for c in ('collector.yuanhang_etfs', 'collector.yuanhang_etf_prices', 'collector.yuanhang_etf_latest'))
        store = get('redis.store')
        catalog.authenticated = AsyncMock(return_value=CATALOG)
        prices.query.scope = AsyncMock(return_value=('2026-11-13', ['2026-11-13']))
        prices.fetch = AsyncMock(return_value=(ROWS, datetime.now(UTC)))
        async def fetch(unit, *, reservation):
            return [r for r in latest_rows() if r['code'] in unit[1]]
        live.fetch = fetch
        async def publish(message):
            async with get('archive.worker').lock:
                state = await prices.ingest.checkpoint(message.job_key)
                await prices.ingest.publish_page([message], job_key=message.job_key,
                    expected_revision=state['revision'], cursor={})
            await get('archive.worker').flush()
        yield manager, catalog, prices, live, store, publish
    finally:
        await manager.shutdown()
        client = create_client(cfg['redis'])
        try:
            keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace']+':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace']+':') for k in keys)
                await client.delete(*keys)
        finally:
            await client.aclose()


async def test_etf_catalog_prices_queries_and_volatile_zero_sql_writes(etfs):
    manager, catalog, prices, live, store, _ = etfs
    await catalog.execute(fresh=True)
    assert await catalog.query.catalog() == CATALOG
    await asyncio.wait_for(prices.execute(fresh=True), 20)
    values = (await prices.query.browse(code='511980.SH'))['rows']
    assert len(values) == 1 and values[0]['close'] == Decimal('100.045') and values[0]['volume'] is None
    for query in (catalog.query, prices.query):
        checks = await query.preparation_check({'codes': ['511980']})
        assert next(c for c in checks if c.criterion == 'coverage').status == 'pass'
    writes = []
    def capture(conn, cursor, sql, *args):
        if sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')):
            writes.append(sql)
    from sqlalchemy.engine import Engine
    event.listen(Engine, 'before_cursor_execute', capture)
    try:
        await live.execute()
        spec = next(s for s in preview_catalog('ths-yuanhang-etf-latest') if s['id'] == 'latest')
        for column in spec['columns']:
            for direction in ('asc', 'desc'):
                page = await preview_read(manager.registry, 'ths-yuanhang-etf-latest', 'latest', {},
                    order={'field': column['key'], 'direction': direction})
                assert page['storage'] == 'Redis 最新行情'
                assert {row['unified_code'] for row in page['rows']} == {r['code'] for r in CATALOG}
        assert not writes
    finally:
        event.remove(Engine, 'before_cursor_execute', capture)
    result = await live.store.browse(limit=1, order={'field': 'latest', 'direction': 'desc'})
    assert result['rows'][0]['unified_code'] == '511980.SH' and result['next']
    assert (await live.store.browse(after=result['next'], limit=1, order={'field': 'latest', 'direction': 'desc'}))['rows'][0]['unified_code'] == '159653.SZ'
    old = result['next']
    await live.execute()
    with pytest.raises(ValueError, match='已更新'):
        await live.store.browse(after=old, limit=1, order={'field': 'latest', 'direction': 'desc'})
    assert await store.client.xlen(store.stream) == 0


async def test_etf_catalog_revision_departure_equal_count_and_late_old(etfs):
    _, catalog, prices, _, store, publish = etfs
    now = datetime.now(UTC)
    await publish(envelope(CATALOG_DATASET, payload={'catalog': CATALOG}, observed=now))
    changed = [dict(CATALOG[0], name='新名称'), dict(code='510010.SH', name='替换目录', native_market='USHJ')]
    await publish(envelope(CATALOG_DATASET, payload={'catalog': changed}, observed=now+timedelta(seconds=2)))
    assert await catalog.query.catalog() == changed
    await publish(envelope(CATALOG_DATASET, payload={'catalog': CATALOG}, observed=now+timedelta(seconds=1)))
    assert await catalog.query.catalog() == changed
    with prices.query.mysql.read_engine.connect() as conn:
        assert not conn.execute(text("SELECT active FROM yuanhang_etf WHERE unified_code='511980.SH'")).scalar_one()
    assert await store.client.xlen(store.stream) == 0


async def test_etf_repeat_hot_cold_zero_dml_revision_and_old_protection(etfs, monkeypatch):
    manager, _, prices, _, store, publish = etfs
    mysql, archive = prices.query.mysql, manager.registry.get('archive.worker')
    now = datetime.now(UTC)
    base = envelope(observed=now)
    await publish(base)
    writes = []
    def capture(conn, cursor, sql, *args):
        if 'yuanhang_etf' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(mysql.archive_engine, 'before_cursor_execute', capture)
    try:
        counted = AsyncMock(wraps=mysql.archive)
        monkeypatch.setattr(mysql, 'archive', counted)
        await publish(base)
        assert not counted.called and not writes
        await archive.fingerprints.invalidate(price_dataset.FINGERPRINT_NAMESPACE, 'ths_yuanhang')
        await publish(base)
        assert counted.called and not writes
        new_rows = [[ROWS[0][0], *['101', '102', '100', '101', '1', '101']]]
        revised = envelope(payload={k: v for k, v in {**base.raw_payload, 'rows': new_rows}.items() if k != 'page'}, observed=now+timedelta(seconds=2))
        await publish(revised)
        assert writes
        size = len(writes)
        await archive.fingerprints.invalidate(price_dataset.FINGERPRINT_NAMESPACE, 'ths_yuanhang')
        await publish(base)
        assert len(writes) == size
        assert (await prices.query.browse(code='511980.SH'))['rows'][0]['close'] == 101
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(mysql.archive_engine, 'before_cursor_execute', capture)


async def test_etf_sql_failure_commit_ack_failure_replays_and_clears(etfs, monkeypatch):
    manager, _, prices, _, store, _ = etfs
    mysql, archive = prices.query.mysql, manager.registry.get('archive.worker')
    original = mysql.archive
    message = envelope()
    async with archive.lock:
        state = await prices.ingest.checkpoint(message.job_key)
        await prices.ingest.publish_page([message], job_key=message.job_key, expected_revision=state['revision'], cursor={})
    monkeypatch.setattr(mysql, 'archive', AsyncMock(side_effect=RuntimeError('SQL unavailable')))
    with pytest.raises(RuntimeError, match='SQL unavailable'):
        await archive.flush()
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(mysql, 'archive', original)
    acknowledge = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ACK unavailable')))
    with pytest.raises(RuntimeError, match='ACK unavailable'):
        await archive.flush()
    assert (await prices.query.browse(code='511980.SH'))['rows']
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive, 'acknowledge', acknowledge)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0


async def test_etf_sql_recovery_and_missing_proof_plans_only_missing(etfs):
    _, catalog, prices, _, store, _ = etfs
    await catalog.execute(fresh=True)
    await prices.execute(fresh=True)
    prices.fetch.reset_mock()
    await prices.execute(baseline_revision=await prices.checkpoint_revision())
    assert not prices.fetch.called
    await store.client.delete(store.prefix+':checkpoint:'+prices.job_key)
    await prices.execute()
    assert not prices.fetch.called
    with prices.query.mysql.archive_engine.begin() as conn:
        conn.execute(text("DELETE FROM yuanhang_etf_price_year WHERE unified_code='511980.SH'"))
    through, trades = await prices.query.scope()
    plans = await prices.query.plans(['511980.SH', '159653.SZ'], through, trades, scope='backfill')
    assert plans['511980.SH']['start'] == '2026-01-01' and plans['159653.SZ']['start'] is None
    assert digest(await catalog.query.catalog()) == digest(CATALOG)
