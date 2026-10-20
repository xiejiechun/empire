"""Owned listing verification: source/content rejection, cancellation and actual SQL."""
import asyncio
import copy
import importlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('verify_listings')


def sample(verifier):
    from empire.features.listings.contract import parse
    from tests.test_ths_listings import STOCKS, source
    return STOCKS[0], parse(source(), STOCKS[0], '2026-10-20')


def test_fixed_source_counterexamples_not_replaced(verifier):
    assert {'301139.SZ', '001381.SZ', '603107.SH', '000032.SZ', '920009.BJ'} <= set(verifier.FIXED_CODES)
    pool = [dict(unified_code=f'{600000+i:06d}.SH', name='样本') for i in range(100)]
    chosen = verifier.verification.select_stocks(pool, 30, 20261020, ['600000.SH'])
    assert len(set(chosen['random'])) == 30 and '600000.SH' in {s['unified_code'] for s in chosen['selected']}
    original_pool, random = copy.deepcopy(chosen['pool']), chosen['random'][:]
    verifier.include_historical_fixed(chosen, None, {})
    assert chosen['pool'] == original_pool and chosen['random'] == random
    assert '301139.SZ' in {s['unified_code'] for s in chosen['selected']}
    assert chosen['historical_fixed']['in_current_pool'] is False


async def test_deferred_source_observer_preserves_budget_ownership(verifier):
    from empire.plugins.collection.unit_prefetch import DeferredResponse
    stock, row = sample(verifier)
    response = SimpleNamespace(close=Mock())
    consume = AsyncMock(return_value=(row, datetime.now(UTC), 'https://example.invalid/'))
    deferred = DeferredResponse(response, consume)
    expected = {}
    wrapped = verifier.observe_fetch(AsyncMock(return_value=deferred), expected)
    assert await wrapped(stock, defer=True) is deferred and not expected
    assert (await deferred.consume())[0] == row
    assert expected[verifier.unit(row)]['row'] == row
    consume.assert_awaited_once()
    response.close.assert_not_called()
    with pytest.raises(ValueError, match='重复'):
        await deferred.consume()


async def test_wrong_stock_identity_rejected(verifier):
    stock, row = sample(verifier)
    wrong = {**row, 'unified_code': '600000.SH'}
    wrapped = verifier.observe_fetch(AsyncMock(return_value=(wrong, datetime.now(UTC), 'url')), {})
    with pytest.raises(ValueError, match='身份'):
        await wrapped(stock)


async def test_equal_count_different_content_rejected_before_commit(verifier):
    from empire.contracts.data import make_envelope
    stock, row = sample(verifier)
    key = verifier.unit(row)
    stamp = datetime.now(UTC)
    e = make_envelope(source='ths', dataset=verifier.DATASET, job_key=verifier.JOB,
        business_key=key, batch_id='test', run_id='test',
        payload=dict(page=1, unit=key, row={**row, 'issuance_price': '99'}, manifest=None))
    e = e.model_copy(update={'observed_at': stamp})
    commit = AsyncMock()
    wrapped = verifier.observe_publish(commit, {key:dict(row=row, observed_at=stamp.isoformat())}, [])
    with pytest.raises(ValueError, match='集合或内容'):
        await wrapped([e], expected_revision=0)
    commit.assert_not_awaited()


async def test_cancel_restores_network_and_observers(verifier):
    ingest = SimpleNamespace(checkpoint=AsyncMock(return_value=dict(revision=0, cursor={})), publish_page=AsyncMock())
    c = SimpleNamespace(ingest=ingest, fetch=AsyncMock(), execute=AsyncMock(side_effect=asyncio.CancelledError()))
    resources = {'collector.ths_listings': c, 'listings.query': object()}
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=resources.__getitem__))
    before = c.fetch, ingest.publish_page, verifier.USE_PROXY.get(), verifier.PROXY_FALLBACK.get()
    with pytest.raises(asyncio.CancelledError):
        await verifier.verify_scope(manager, dict(selected=[]), SimpleNamespace(proxy_only=True), dict(results={}))
    assert before == (c.fetch, ingest.publish_page, verifier.USE_PROXY.get(), verifier.PROXY_FALLBACK.get())


def test_capacity_only_exact_sql_after_actual_identity_guard(verifier):
    capacity = importlib.import_module('measure_listings')
    storage = capacity.ListingCapacityStorage(dict(host='test', port=13348, user='test'), {},
                                            'a'*32, 'b'*64, 'production')
    storage.server_uuid = 'test-instance'
    connection = Mock()
    connection.engine.url.database = storage.database
    raw = connection.connection.cursor.return_value
    raw.fetchone.return_value = ('test-instance', storage.database)
    for sql in ('ANALYZE TABLE stock_listing', *('EXPLAIN '+q for q in capacity.CAPACITY_QUERIES.values())):
        storage.guard(connection, None, sql, (), None, False)
    assert raw.execute.call_count == 5
    for sql in ('ANALYZE TABLE stock', 'EXPLAIN SELECT * FROM stock_listing',
                'ANALYZE TABLE stock_listing; DELETE FROM stock', 'EXPLAIN SELECT * FROM empire.stock_listing'):
        with pytest.raises(ValueError):
            storage.guard(connection, None, sql, (), None, False)
    raw.fetchone.return_value = ('production', storage.database)
    with pytest.raises(ValueError, match='实际实例'):
        storage.guard(connection, None, 'ANALYZE TABLE stock_listing', (), None, False)


@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Actual owned SQL/Redis opt-in')
async def test_actual_guarded_source_status_and_public_queries(verifier):
    import httpx
    from source_test_storage import PrivateStorage, read_server_uuid
    from source_verification import finish

    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from tests.prefetch_source import prefetch_http
    from tests.test_ths_listings import source

    cfg = load_config()
    test = json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf-8'))
    storage = PrivateStorage(test, cfg['redis'], uuid4().hex, token_hex(32), read_server_uuid(cfg['mysql']))
    manager, cleanup = None, dict(cleanup={}, errors=[])
    stocks = [dict(unified_code=code, name='隔离样本') for code in ('000001.SZ', '001381.SZ', '301139.SZ')]
    try:
        storage.create_sql()
        await storage.create_redis()
        storage.seed(stocks, [])
        test_cfg = copy.deepcopy(cfg)
        test_cfg['mysql'], test_cfg['redis']['namespace'] = storage.settings, storage.namespace
        manager = build_manager(test_cfg)
        await manager.start('pipeline.archive')
        await manager.start('collector.ths_listings')
        c = manager.registry.get('collector.ths_listings')
        c.session = SimpleNamespace(headers=lambda _: {})
        def response(method, url, **kwargs):
            body = source()
            if '001381' in url:
                body['data']['listing_date'] = None
            if '301139' in url:
                body = dict(status_code=10001, status_msg='result empty', data={})
            return httpx.Response(200, json=body)
        c.http = prefetch_http(request=AsyncMock(side_effect=response))
        report = dict(results={})
        await verifier.verify_scope(manager, dict(selected=stocks), SimpleNamespace(proxy_only=False), report)
        result = report['results']['listings']
        assert result['pipeline_verified'] and result['acceptance_complete'] and result['pending'] == 0
        assert not result['strict_proxy_verified']
        assert len(result['query_units']) == 3
        assert {v['status'] for v in result['source_units'].values()} == {'available', 'incomplete', 'unavailable'}
        assert any(v['status'] == 'fail' for v in result['preparation'])
    finally:
        await finish(manager, storage, None, cleanup, Redactor([storage.owner]))
    assert not cleanup['errors'] and all(cleanup['cleanup'].values())
