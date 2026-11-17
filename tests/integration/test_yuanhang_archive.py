"""Native history → shared queue/archive → formal SQL query, with private ownership."""
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import event

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.yuanhang.contract import PRICE_JOB
from empire.plugins.infra.routing import USE_PROXY
from empire.sources.yuanhang_service import YuanhangIdentityPlugin
from empire.sources.yuanhang_sessions import NodeSessions
from tests.test_yuanhang_payload import CODE, bar, snapshot
from tests.test_yuanhang_storage import envelope

pytestmark = [pytest.mark.integration,
    pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit private database')]


@pytest.fixture
async def native(monkeypatch):
    identity = SimpleNamespace(sessions=NodeSessions(), get_profiles=AsyncMock(return_value={
        'node-test': SimpleNamespace(provisioned=True)}), online_codes=lambda: {'node-test'})
    async def start(self, context):
        return {'yuanhang.identity': identity}
    monkeypatch.setattr(YuanhangIdentityPlugin, 'start', start)
    cfg = load_config()
    manager = build_manager(cfg)
    store = None
    token = USE_PROXY.set(True)
    try:
        await manager.start('collector.yuanhang_prices')
        c, q, store, archive = (manager.registry.get(k) for k in (
            'collector.yuanhang_prices', 'yuanhang.history.query', 'redis.store', 'archive.worker'))
        # Synthetic complete calendar for lifecycle tests, not production weekend
        # inference. The fixture cutoff is intentionally declared a trading day.
        from datetime import date

        from sqlalchemy import text
        first, last = date(1990, 12, 19), date(2023, 12, 31)
        with q.mysql.engine.begin() as conn:
            conn.execute(text('INSERT INTO trade_calendar(trade_date,is_trade,updated_at) VALUES(:day,:trade,:updated)'),
                         [dict(day=first + timedelta(days=i), trade=1, updated='2023-12-31')
                          for i in range((last-first).days+1)])
        c.query.collection_scope = AsyncMock(return_value=([CODE], '2023-12-31'))
        c.fetch = AsyncMock(return_value=snapshot((bar('2020-10-19'), bar('2022-01-04'))))
        yield manager, c, q, store, archive
    finally:
        await manager.shutdown()
        USE_PROXY.reset(token)
        if store:
            from empire.plugins.infra.redis_store import create_client
            client = create_client(cfg['redis'])
            keys = [k async for k in client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith(cfg['redis']['namespace'] + ':') for k in keys)
                await client.delete(*keys)
            await client.aclose()


async def publish(c, archive, e):
    checkpoint = await c.ingest.checkpoint(e.job_key)
    await c.ingest.publish_page([e], job_key=e.job_key, expected_revision=checkpoint['revision'], cursor=dict(test=True))
    await archive.flush()


async def test_collector_publishes_years_without_per_batch_archive_wait_and_cleans_queue(native):
    _, c, q, store, archive = native
    original, before_wait = c.confirmation.page_status, []
    async def status(*args):
        # Reaching the only wait must happen after all four annual messages exist.
        before_wait.append((await c.ingest.checkpoint(PRICE_JOB))['cursor']['pages'])
        await archive.flush()
        return await original(*args)
    c.confirmation.page_status = status
    try:
        result = await c.execute()
    finally:
        c.confirmation.page_status = original
    assert result['phase'] == 'complete' and result['pages'] == 4
    assert before_wait and set(before_wait) == {4}
    assert set(await q.year_heads(CODE)) == {2020, 2021, 2022, 2023}
    assert len((await q.prices(CODE))['rows']) == 2
    assert await store.client.xlen(store.stream) == 0


async def test_hot_fingerprint_is_sql_free_and_cold_duplicate_or_stale_cleans_message(native):
    _, c, q, store, archive = native
    e = envelope()
    await publish(c, archive, e)
    async def fail(*args, **kwargs):
        raise AssertionError('hot fingerprint must not access SQL')
    original = archive.mysql.archive
    archive.mysql.archive = fail
    try:
        await publish(c, archive, e.model_copy(update=dict(observed_at=e.observed_at + timedelta(minutes=1))))
        assert await store.client.xlen(store.stream) == 0
    finally:
        archive.mysql.archive = original
    # Remove only this dataset's trusted fingerprints in this test's own namespace.
    keys = [k async for k in store.client.scan_iter(match=store.prefix + ':archive:fingerprint*')]
    if keys:
        await store.client.delete(*keys)
    business_dml = []
    def count(conn, cursor, sql, *args):
        if sql.startswith(('INSERT INTO yuanhang_', 'DELETE FROM yuanhang_', 'UPDATE yuanhang_')):
            business_dml.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', count)
    event.listen(q.mysql.archive_engine, 'before_cursor_execute', count)
    try:
        await publish(c, archive, e)
        await publish(c, archive, e.model_copy(update=dict(observed_at=e.observed_at - timedelta(hours=1))))
        assert business_dml == [] and await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', count)
        event.remove(q.mysql.archive_engine, 'before_cursor_execute', count)


async def test_source_validation_failure_keeps_resume_position(native):
    _, c, _, store, _ = native
    c.fetch = AsyncMock(side_effect=ValueError('bad native fixture'))
    with pytest.raises(ValueError, match='bad native'):
        await c.execute()
    state = await c.ingest.checkpoint(PRICE_JOB)
    assert not state['cursor'] or state['cursor'].get('next_index', 0) == 0
    assert await store.client.xlen(store.stream) == 0


async def test_node_unavailable_evidence_reaches_redis_without_advancing(native):
    import httpx

    from empire.features.yuanhang.node_diagnostics import failure

    _, c, _, store, _ = native
    error = ValueError('远航节点不可用；最后失败节点：node-test')
    error.yuanhang_diagnostics = dict(security=CODE, required_node='node-test',
        failures=[failure('node-test', httpx.ProxyError('user:secret@host'), 3)],
        wait_started=dict(counts={'cooldown': 1}), wait_finished=dict(counts={'missing_directory': 1}))
    c.fetch = AsyncMock(side_effect=error)
    with pytest.raises(ValueError, match='node-test'):
        await c.execute()
    summary = await c.records.list_error_summaries(c.project_id)
    record = await c.records.get_error(c.project_id, summary['rows'][0]['id'])
    assert record['metadata'] == error.yuanhang_diagnostics
    assert 'secret' not in str(record)
    state = await c.ingest.checkpoint(PRICE_JOB)
    assert state['cursor']['next_index'] == 0 and state['cursor']['pages'] == 0
    assert await store.client.xlen(store.stream) == 0


async def test_persistent_financial_null_never_publishes_or_advances(native, monkeypatch):
    from empire.features.yuanhang import collector as module
    from empire.features.yuanhang.contract import FINANCIAL_JOB
    from empire.sources.yuanhang_history import MissingFinancialValue

    manager, _, q, store, _ = native
    await manager.start('collector.yuanhang_financial')
    c = manager.registry.get('collector.yuanhang_financial')
    c.request_retries = 1
    c.identity.login = AsyncMock(return_value=SimpleNamespace(proxy_code='node-test'))
    def missing_value():
        error = MissingFinancialValue(402, '2023-01-01', CODE)
        error.yuanhang_diagnostics = dict(response_sha256='a' * 64, response_bytes=42,
            null_tables=[dict(row_count=1, descriptor=[402, 3, 0, 8], null_dates=[20230101])])
        return error
    wire = AsyncMock(side_effect=[missing_value(), missing_value()])
    monkeypatch.setattr(module, 'fetch_history', wire)
    monkeypatch.setattr(module, 'retry_delay', lambda _: 0)
    before = await c.ingest.checkpoint(FINANCIAL_JOB)
    with pytest.raises(MissingFinancialValue, match='field=402'):
        await c.execute()
    assert wire.await_count == 2
    assert [call.kwargs['fresh_connection'] for call in wire.await_args_list] == [False, True]
    errors = await c.records.list_error_summaries(c.project_id)
    record = await c.records.get_error(c.project_id, errors['rows'][0]['id'])
    assert record['metadata']['confirmation_attempted'] is True
    observations = record['metadata']['null_observations']
    assert len(observations) == 2
    assert all(row['node'] == 'node-test' and row['field'] == 402 for row in observations)
    assert all(row['response_sha256'] == 'a' * 64 for row in observations)
    assert record['metadata']['null_tables'] == [dict(row_count=1,
        descriptor=[402, 3, 0, 8], null_dates=[20230101])]
    assert await c.ingest.checkpoint(FINANCIAL_JOB) == before
    assert not await q.has_history(CODE, financial=True)
    assert await store.client.xlen(store.stream) == 0


async def test_partial_archive_resume_keeps_current_full_plan_without_pool_plan_checkpoint(native):
    import json
    from datetime import date

    from empire.sources.yuanhang_payload import daily_years

    _, c, q, store, archive = native
    publish = c.ingest.publish_page
    async def interrupt(messages, **kwargs):
        if kwargs['cursor']['pages'] == 2:
            raise ValueError('fixture checkpoint interruption')
        return await publish(messages, **kwargs)
    c.ingest.publish_page = interrupt
    try:
        with pytest.raises(ValueError, match='checkpoint interruption'):
            await c.execute()
    finally:
        c.ingest.publish_page = publish
    state = await c.ingest.checkpoint(PRICE_JOB)
    assert state['cursor']['next_index'] == 0 and state['cursor']['next_year'] == 2021
    assert state['cursor']['current_plan']['mode'] == 'full'
    assert len(json.dumps(state['cursor']).encode()) < 16384
    assert 'plans' not in state['cursor'] and 'work_codes' not in state['cursor']
    await archive.flush()
    assert set(await q.year_heads(CODE)) == {2020}
    original_plans = q.daily_plans
    q.daily_plans = AsyncMock(side_effect=AssertionError('Pinned current security must not be replanned'))
    try:
        result = await c.execute()
    finally:
        q.daily_plans = original_plans
    assert result['pages'] == 4 and result['phase'] == 'complete'
    for payload in daily_years(c.fetch.return_value, code=CODE, through=date(2023,12,31)):
        assert await q.audit_price(payload) == []
    assert await store.client.xlen(store.stream) == 0


async def test_complete_wire_repeats_reach_formal_query_once_and_replay_without_business_dml(native):
    from datetime import date

    from empire.sources.yuanhang_payload import daily_years
    from tests.test_yuanhang_daily_repeats import normalized_daily, raw_bar

    _, c, q, store, _ = native
    bars = normalized_daily([raw_bar(), raw_bar(), raw_bar(20221011)])
    c.fetch = AsyncMock(return_value=snapshot(bars))
    result = await c.execute()
    assert result['phase'] == 'complete'
    rows = (await q.prices(CODE))['rows']
    assert [r['trade_date'].isoformat() for r in rows] == ['2022-10-10','2022-10-11']
    assert await store.client.xlen(store.stream) == 0
    for p in daily_years(snapshot(bars), code=CODE, through=date(2023,12,31)):
        assert await q.audit_price(p) == []
    dml = []
    def count(conn, cursor, sql, *args):
        if sql.startswith(('INSERT INTO yuanhang_', 'DELETE FROM yuanhang_', 'UPDATE yuanhang_')):
            dml.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', count)
    event.listen(q.mysql.archive_engine, 'before_cursor_execute', count)
    try:
        c.fetch = AsyncMock(return_value=snapshot(normalized_daily([raw_bar(), raw_bar(20221011)])))
        await c.execute(baseline_revision=await c.checkpoint_revision())
        assert dml == [] and await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', count)
        event.remove(q.mysql.archive_engine, 'before_cursor_execute', count)


async def test_conflicting_wire_repeat_preserves_checkpoint_and_existing_formal_rows(native):
    from tests.test_yuanhang_daily_repeats import normalized_daily, raw_bar

    _, c, q, store, _ = native
    await c.execute()
    old = await c.ingest.checkpoint(PRICE_JOB)
    before = await q.prices(CODE)
    async def conflicting(*args, **kwargs):
        return snapshot(normalized_daily([raw_bar(), {**raw_bar(), 11: 34.}]))
    c.fetch = conflicting
    with pytest.raises(ValueError, match='duplicate'):
        await c.execute(fresh=True, baseline_revision=await c.checkpoint_revision())
    assert await c.ingest.checkpoint(PRICE_JOB) == old
    assert await q.prices(CODE) == before
    assert await store.client.xlen(store.stream) == 0


async def test_explicit_prelisting_has_no_fake_business_and_next_round_collects_after_listing(native, monkeypatch):
    import httpx

    from empire.features.yuanhang import collector as module
    from empire.sources.yuanhang_wire import EmptyHistoryResponse

    _, c, q, store, archive = native
    c.fetch = module.YuanhangCollector.fetch.__get__(c)
    c.identity.login = AsyncMock(return_value=SimpleNamespace(proxy_code='node-test'))
    wire = AsyncMock(side_effect=EmptyHistoryResponse(1, 210))
    monkeypatch.setattr(module, 'fetch_history', wire)
    async def metadata(*args, **kwargs):
        assert kwargs['params']['filter'] == f'(SECUCODE="{CODE}")'
        return httpx.Response(200, json=dict(success=True, result=dict(count=1, pages=1, data=[
            dict(SECUCODE=CODE, SECURITY_CODE=CODE[:6], LISTING_STATE='9', LISTING_DATE=None)])))
    monkeypatch.setattr(c.http, 'request', metadata)
    result = await c.execute()
    assert result['phase'] == 'complete' and result['pages'] == 0
    assert set(result['deferred']) == {CODE}
    assert not await q.has_history(CODE)
    assert (await q.prices(CODE))['rows'] == []
    assert await store.client.xlen(store.stream) == 0
    wire.side_effect = None
    wire.return_value = snapshot((bar('2020-10-19'), bar('2022-01-04')))
    result = await c.execute(baseline_revision=await c.checkpoint_revision())
    assert result['phase'] == 'complete' and result['deferred'] == {} and result['pages'] == 4
    assert await q.has_history(CODE)
    assert len((await q.prices(CODE))['rows']) == 2
    assert await store.client.xlen(store.stream) == 0


async def test_prelisting_metadata_failure_never_advances_checkpoint(native, monkeypatch):
    import httpx

    from empire.features.yuanhang import collector as module
    from empire.sources.yuanhang_wire import EmptyHistoryResponse

    _, c, _, store, _ = native
    c.fetch = module.YuanhangCollector.fetch.__get__(c)
    c.identity.login = AsyncMock(return_value=SimpleNamespace(proxy_code='node-test'))
    monkeypatch.setattr(module, 'fetch_history', AsyncMock(side_effect=EmptyHistoryResponse(1, 210)))
    monkeypatch.setattr(c.http, 'request', AsyncMock(return_value=httpx.Response(200,
        json=dict(success=True, result=dict(count=1, pages=1, data=[])))))
    with pytest.raises(ValueError):
        await c.execute()
    state = await c.ingest.checkpoint(PRICE_JOB)
    assert not state['cursor'] or state['cursor'].get('next_index', 0) == 0
    assert await store.client.xlen(store.stream) == 0


async def test_partial_financial_prelisting_creates_no_fact_then_recovers(native, monkeypatch):
    from datetime import date

    import httpx

    from empire.features.yuanhang import collector as module
    from empire.sources.yuanhang_history import (
        CapitalPoint,
        FinancialHistory,
        IncompleteFinancialHistory,
    )
    from tests.test_yuanhang_payload import snapshot

    manager, _, q, store, _ = native
    await manager.start('collector.yuanhang_financial')
    c = manager.registry.get('collector.yuanhang_financial')
    c.identity.login = AsyncMock(return_value=SimpleNamespace(proxy_code='node-test'))
    wire = AsyncMock(side_effect=IncompleteFinancialHistory(CODE, date(2023, 1, 1)))
    monkeypatch.setattr(module, 'fetch_history', wire)
    monkeypatch.setattr(c.http, 'request', AsyncMock(return_value=httpx.Response(200,
        json=dict(success=True, result=dict(count=1, pages=1, data=[dict(
            SECUCODE=CODE, SECURITY_CODE=CODE[:6], LISTING_STATE='9', LISTING_DATE=None)])))))
    result = await c.execute()
    assert result['pages'] == 0 and result['phase'] == 'complete'
    assert result['deferred'][CODE]['native_status'] == 'partial_total_circulating'
    assert not await q.has_history(CODE, financial=True)
    assert await store.client.xlen(store.stream) == 0

    from decimal import Decimal
    wire.side_effect = None
    wire.return_value = snapshot(FinancialHistory((), tuple(
        CapitalPoint(CODE, date(2023, 1, 1), kind, Decimal('100'))
        for kind in ('circulating', 'free_float', 'total'))))
    result = await c.execute(baseline_revision=await c.checkpoint_revision())
    assert result['pages'] == 1 and result['phase'] == 'complete' and result['deferred'] == {}
    assert await q.has_history(CODE, financial=True)
    assert await store.client.xlen(store.stream) == 0


async def test_initial_capital_gap_archives_sibling_and_recovers_only_missing_security(native, monkeypatch):
    from datetime import date

    import httpx

    from empire.contracts.collector import CollectionSourceGap
    from empire.features.yuanhang import collector as module
    from empire.sources.yuanhang_client import HistorySnapshot
    from empire.sources.yuanhang_history import normalize_financial
    from empire.sources.yuanhang_payload import financial_payload
    from tests.test_yuanhang_history import tables

    manager, _, query, store, _ = native
    await manager.start('collector.yuanhang_financial')
    c = manager.registry.get('collector.yuanhang_financial')
    query.collection_scope = AsyncMock(return_value=(['000001.SZ', CODE], '2023-12-31'))
    c.identity.login = AsyncMock(return_value=SimpleNamespace(proxy_code='node-test'))
    complete = False
    sources = {}
    async def fetch(http, session, *, unified_code, **kwargs):
        market = 'USHA' if unified_code.endswith('.SH') else 'USZA'
        row = {1: 20231101, 402: 100., 407: 10.}
        if unified_code != CODE or complete:
            row[380] = 8.
        data = normalize_financial(tables([row], market + unified_code[:6]), unified_code=unified_code,
                                  start=date(1900, 1, 1), end=date(2100, 12, 31))
        result = HistorySnapshot(market, snapshot(()).observed_at, data)
        sources[unified_code] = financial_payload(result, code=unified_code)
        return result
    wire = AsyncMock(side_effect=fetch)
    monkeypatch.setattr(module, 'fetch_history', wire)
    metadata = AsyncMock(return_value=httpx.Response(200, json=dict(success=True,
        result=dict(count=1, pages=1, data=[dict(SECUCODE=CODE, SECURITY_CODE=CODE[:6],
            LISTING_STATE='0', LISTING_DATE='2023-11-01 00:00:00')]))))
    monkeypatch.setattr(c.http, 'request', metadata)
    for run in range(2):
        wire.reset_mock()
        with pytest.raises(CollectionSourceGap, match=CODE):
            await c.execute(baseline_revision=await c.checkpoint_revision())
        assert [call.kwargs['unified_code'] for call in wire.await_args_list] == (['000001.SZ', CODE] if not run else [CODE])
        state = await c.ingest.checkpoint(c.job_key)
        assert state['cursor']['phase'] == 'source_gap'
        assert state['cursor']['deferred'][CODE]['node'] == 'node-test'
        assert not await query.has_history(CODE, financial=True)
        assert await query.has_history('000001.SZ', financial=True)
        assert await query.audit_financial(sources['000001.SZ']) == []
        assert await store.client.xlen(store.stream) == 0
    complete = True
    wire.reset_mock()
    result = await c.execute(baseline_revision=await c.checkpoint_revision())
    assert result['phase'] == 'complete' and result['deferred'] == {}
    assert [call.kwargs['unified_code'] for call in wire.await_args_list] == [CODE]
    assert metadata.await_count == 2
    assert await query.audit_financial(sources[CODE]) == []
    assert (await query.capital_points(CODE, 'free_float'))['rows'][0]['shares'] == 8
    assert await store.client.xlen(store.stream) == 0


async def test_native_null_volume_reaches_queue_archive_formal_query_and_replay(native):
    from dataclasses import replace

    from empire.sources.yuanhang_payload import daily_years

    _, c, q, store, archive = native
    from datetime import date
    source = snapshot((replace(bar('2020-10-19'), volume_shares=None),))
    c.fetch = AsyncMock(return_value=source)
    await c.execute()
    row, = (await q.prices(CODE))['rows']
    assert row['volume_shares'] is row['amount_yuan'] is None
    assert (await q.price_quality(CODE))['missing_volume'] == 1
    assert await q.audit_price(daily_years(source, code=CODE, through=date(2023,12,31))[0]) == []
    writes = []
    def count(conn, cursor, sql, *args):
        if sql.startswith(('INSERT INTO yuanhang_', 'UPDATE yuanhang_', 'DELETE FROM yuanhang_')):
            writes.append(sql)
    event.listen(q.mysql.engine, 'before_cursor_execute', count)
    event.listen(q.mysql.archive_engine, 'before_cursor_execute', count)
    try:
        await c.execute(baseline_revision=await c.checkpoint_revision())
        assert not writes and await store.client.xlen(store.stream) == 0
    finally:
        event.remove(q.mysql.engine, 'before_cursor_execute', count)
        event.remove(q.mysql.archive_engine, 'before_cursor_execute', count)


async def test_initialization_resumes_source_audit_without_redownloading_published_prefix(native, monkeypatch):
    from datetime import date
    from decimal import Decimal

    import httpx

    from empire.sources.yuanhang_history import CapitalPoint, FinancialHistory
    from scripts import initialize_yuanhang_history as initialization

    manager, c, q, _, _ = native
    codes = [CODE, '605337.SH']
    q.collection_scope = AsyncMock(return_value=(codes, '2023-12-31'))
    monkeypatch.setattr(initialization, 'build_manager', lambda cfg: manager)
    calls, fail = [], True
    async def prices(unit, *, reservation=None):
        calls.append(unit[0])
        if fail and unit[0] == codes[1]:
            raise httpx.ConnectError('fixture interrupted source')
        return snapshot((bar('2020-10-19', code=unit[0]),))
    async def financial(unit, *, reservation=None):
        return snapshot(FinancialHistory((), tuple(CapitalPoint(unit[0], date(2020,1,1), kind, Decimal('100'))
                       for kind in ('circulating','free_float','total'))))
    c.fetch = prices
    manager.entries['collector.yuanhang_financial'].plugin.fetch = financial
    prior = {}
    with pytest.raises(httpx.ConnectError):
        await initialization.initialize(load_config(), prior, apply=True)
    assert set(prior['audit_sources']['ths-yuanhang-prices']['proofs']) == {CODE}
    fail = False
    report = {}
    await initialization.initialize(load_config(), report, apply=True, resume=prior)
    assert report['initialization_complete']
    assert calls.count(CODE) == 1 and calls.count(codes[1]) == 2
    assert all(not s['problems'] for d in report['datasets'].values() for s in d['securities'])
