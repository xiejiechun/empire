"""Three native/web projects through private Redis, SQL archive and formal reads."""
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
from empire.core.config import load_config
from empire.features.yuanhang_indices import member_dataset, price_dataset
from empire.features.yuanhang_indices.contract import PRICE_DATASET
from tests.test_yuanhang_indices import CATALOG, ROWS, configured, envelope

pytestmark = [pytest.mark.integration, pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Private SQL opt-in')]


@pytest.fixture
async def indices():
    cfg = copy.deepcopy(load_config())
    cfg['redis']['namespace'] = 'empire:test:' + uuid4().hex
    manager, store = build_manager(cfg), None
    try:
        for capability in ('collector.yuanhang_indices', 'collector.yuanhang_index_members', 'collector.yuanhang_index_prices'):
            await manager.start(capability)
        get = manager.registry.get
        catalog, members, prices = (get(c) for c in ('collector.yuanhang_indices', 'collector.yuanhang_index_members', 'collector.yuanhang_index_prices'))
        store = get('redis.store')
        catalog.authenticated = AsyncMock(return_value=CATALOG)
        members.session = SimpleNamespace(headers=lambda _: {})
        members.http = configured().http
        prices.query.scope = AsyncMock(return_value=('2026-11-13', ['2026-11-12', '2026-11-13']))
        prices.fetch = AsyncMock(return_value=(ROWS, datetime.now(UTC)))
        async def publish(message):
            state = await members.ingest.checkpoint(message.job_key)
            await members.ingest.publish_page([message], job_key=message.job_key,
                expected_revision=state['revision'], cursor={'test': True})
            await get('archive.worker').flush()
        yield manager, catalog, members, prices, store, publish
    finally:
        await manager.shutdown()
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            try:
                keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
                if keys:
                    assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                    await client.delete(*keys)
            finally:
                await client.aclose()


async def initialize(catalog, members):
    await asyncio.wait_for(catalog.execute(fresh=True), 20)
    await asyncio.wait_for(members.execute(fresh=True), 20)


async def test_three_tasks_source_archive_query_and_scoped_preparation(indices):
    manager, catalog, members, prices, store, _ = indices
    await initialize(catalog, members)
    await asyncio.wait_for(prices.execute(fresh=True), 20)
    assert len(await catalog.query.catalog()) == 2
    row = (await members.query.browse('indices', selected_index='899050'))['rows'][0]
    assert row['members_available'] == 0 and row['member_count'] is None
    assert not (await members.query.browse('members', selected_index='899050'))['rows']
    assert (await members.query.browse('members', search='000001'))['rows'][0]['unified_code'] == '000001.SZ'
    values = (await prices.query.browse(code='1A0001'))['rows']
    assert values[0]['low'] is None and values[0]['amount'] == -1
    for query in (catalog.query, members.query, prices.query):
        checks = await query.preparation_check({'index_codes': ['1A0001'], 'start': '2026-11-01', 'end': '2026-11-13'})
        assert {c.criterion for c in checks} == {'fields', 'keys', 'coverage', 'quality', 'freshness', 'temporal'}
        assert next(c for c in checks if c.criterion == 'coverage').status == 'pass'
    checks = await members.query.preparation_check({'index_codes': ['899050']})
    assert next(c for c in checks if c.criterion == 'coverage').status == 'pass'
    assert await store.client.xlen(store.stream) == 0
    assert manager.registry.get('indices.query') is members.query


async def test_member_hot_cold_no_dml_revision_old_empty_restore(indices, monkeypatch):
    manager, catalog, members, _, store, publish = indices
    await initialize(catalog, members)
    archive, mysql = manager.registry.get('archive.worker'), members.query.mysql
    writes = []
    def capture(conn, cursor, sql, params, context, many):
        if 'ths_index_member' in sql and sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')):
            writes.append(sql)
    event.listen(mysql.archive_engine, 'before_cursor_execute', capture)
    try:
        now = datetime.now(UTC) + timedelta(seconds=1)
        base = envelope(payload=dict(code='1A0001', available=True,
            members=[['000001', '样本证券'], ['600000', '样本证券']])).model_copy(update={'observed_at': now})
        original = mysql.archive
        counted = AsyncMock(wraps=original)
        monkeypatch.setattr(mysql, 'archive', counted)
        await publish(base)
        assert not counted.called and not writes
        await archive.fingerprints.invalidate(member_dataset.FINGERPRINT_NAMESPACE, 'ths')
        await publish(base)
        assert counted.called and not writes
        changed = envelope(payload=dict(code='1A0001', available=True,
            members=[['000002', '修订'], ['600000', '样本证券']])).model_copy(update={'observed_at': now+timedelta(seconds=2)})
        await publish(changed)
        assert len((await members.query.browse('members', search='000002'))['rows']) == 1
        size = len(writes)
        await archive.fingerprints.invalidate(member_dataset.FINGERPRINT_NAMESPACE, 'ths')
        await publish(base)
        assert len(writes) == size
        empty = envelope(payload=dict(code='1A0001', available=False, members=[])).model_copy(update={'observed_at': now+timedelta(seconds=3)})
        await publish(empty)
        assert not (await members.query.browse('members', selected_index='1A0001'))['rows']
        await publish(changed.model_copy(update={'observed_at': now+timedelta(seconds=4)}))
        assert (await members.query.browse('members', search='000002'))['rows']
        assert await store.client.xlen(store.stream) == 0
    finally:
        event.remove(mysql.archive_engine, 'before_cursor_execute', capture)


async def test_member_sql_failure_commit_ack_replay(indices, monkeypatch):
    manager, catalog, members, _, store, _ = indices
    await initialize(catalog, members)
    archive, mysql = manager.registry.get('archive.worker'), members.query.mysql
    original = mysql.archive
    message = envelope(payload=dict(code='1A0001', available=True, members=[['600000', '新版']]))
    async with archive.lock:
        state = await members.ingest.checkpoint(message.job_key)
        await members.ingest.publish_page([message], job_key=message.job_key, expected_revision=state['revision'], cursor={})
    monkeypatch.setattr(mysql, 'archive', AsyncMock(side_effect=RuntimeError('SQL unavailable')))
    with pytest.raises(RuntimeError, match='SQL unavailable'):
        await archive.flush()
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(mysql, 'archive', original)
    acknowledge = archive.acknowledge
    monkeypatch.setattr(archive, 'acknowledge', AsyncMock(side_effect=RuntimeError('ACK unavailable')))
    with pytest.raises(RuntimeError, match='ACK unavailable'):
        await archive.flush()
    assert (await members.query.browse('members', search='新版'))['rows']
    assert await store.client.xlen(store.stream) == 1
    monkeypatch.setattr(archive, 'acknowledge', acknowledge)
    await archive.flush()
    assert await store.client.xlen(store.stream) == 0


async def test_recent_is_not_full_history_and_old_overlap_cannot_undo_new_day(indices):
    manager, catalog, _, prices, store, publish = indices
    await asyncio.wait_for(catalog.execute(fresh=True), 20)
    now = datetime.now(UTC)
    def price(rows, observed, *, start='2026-11-01', full=False):
        return envelope(PRICE_DATASET, payload=dict(code='1A0001', native_market='USHI',
            start=start, through='2026-11-13', rows=rows, full=full,
            history_start='2026-11-13' if full else None)).model_copy(update={'observed_at': observed})
    await publish(price(ROWS, now))
    checks = await prices.query.preparation_check({'index_codes': ['1A0001']})
    assert next(c for c in checks if c.criterion == 'coverage').status == 'fail'
    checks = await prices.query.preparation_check({'index_codes': ['1A0001'], 'start': '2026-11-01', 'end': '2026-11-13'})
    assert next(c for c in checks if c.criterion == 'coverage').status == 'pass'
    newer = [[ROWS[0][0], *['20', '21', '19', '20', '1', '2']]]
    await publish(price(newer, now+timedelta(seconds=3)))
    await manager.registry.get('archive.worker').fingerprints.invalidate(price_dataset.FINGERPRINT_NAMESPACE, 'ths_yuanhang')
    await publish(price(ROWS, now+timedelta(seconds=1), start='2026-01-01', full=True))
    assert (await prices.query.browse(code='1A0001'))['rows'][0]['close'] == 20
    with prices.query.mysql.read_engine.connect() as conn:
        stamp = conn.execute(text("SELECT version_observed_at FROM yuanhang_index_price_year WHERE index_code='1A0001' AND quote_year=2026")).scalar_one()
        assert stamp >= (now+timedelta(seconds=3)).astimezone(__import__('empire.core.time', fromlist=['CHINA']).CHINA).replace(tzinfo=None)
    assert await store.client.xlen(store.stream) == 0


async def test_daily_budget_sql_recovery_and_missing_head_cannot_skip(indices):
    _, catalog, _, prices, store, _ = indices
    await catalog.execute(fresh=True)
    through, trades = await prices.query.scope()
    # An uninitialized security requests a recent prefix and one historical unit.
    plans = await prices.query.plans(['1A0001'], through, trades)
    assert plans['1A0001']['start'] == '2026-01-01'
    await prices.execute(fresh=True)
    prices.fetch.reset_mock()
    await prices.execute(baseline_revision=await prices.checkpoint_revision())
    assert not prices.fetch.called
    await store.client.delete(store.prefix+':checkpoint:'+prices.job_key)
    await prices.execute()
    assert not prices.fetch.called
    with prices.query.mysql.archive_engine.begin() as conn:
        conn.execute(text("DELETE FROM yuanhang_index_price_year WHERE index_code='1A0001'"))
    recent = await prices.query.plans(['1A0001'], through, trades)
    historical = await prices.query.plans(['1A0001'], through, trades, scope='backfill')
    assert recent['1A0001']['start'] and historical['1A0001']['start'] == '2026-01-01'
