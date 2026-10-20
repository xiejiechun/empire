"""Month verification rejects false sets and preserves guarded cleanup ownership."""
import asyncio
import copy
import importlib
import json
import os
from datetime import date
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest


@pytest.fixture
def verifier(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('verify_listing_status')


async def test_deferred_observation_retains_response_and_rejects_double_consume(verifier):
    from empire.plugins.collection.unit_prefetch import DeferredResponse
    response = SimpleNamespace(close=Mock())
    deferred = DeferredResponse(response, AsyncMock(return_value=([], 0)))
    daily = {}
    wrapped = verifier.observe_fetch(AsyncMock(return_value=deferred), daily)
    assert await wrapped('2020-05-01', defer=True) is deferred and not daily
    assert await deferred.consume() == ([], 0)
    assert daily == {'2020-05-01': ([], 0)}
    response.close.assert_not_called()
    with pytest.raises(ValueError, match='重复'):
        await deferred.consume()


async def test_equal_count_different_month_content_never_committed(verifier):
    from tests.test_listing_status import envelope
    e = envelope()
    daily = {f'2001-06-{i:02}': ([], 0) for i in range(1, 31)}
    wrong = copy.deepcopy(e.raw_payload['rows'])
    wrong[0][4] = '不同名称'
    daily['2001-06-15'] = (wrong, 1)
    commit = AsyncMock()
    wrapped = verifier.observe_publish(commit, daily, [], date(2001, 6, 30))
    with pytest.raises(ValueError, match='集合或内容'):
        await wrapped([e], expected_revision=0)
    commit.assert_not_awaited()


async def test_missing_day_cannot_prove_empty_month(verifier):
    from tests.test_listing_status import envelope
    commit = AsyncMock()
    wrapped = verifier.observe_publish(commit, {}, [], date(2001, 6, 30))
    with pytest.raises(KeyError):
        await wrapped([envelope()], expected_revision=0)
    commit.assert_not_awaited()


async def test_cancel_restores_query_fetch_publish_and_network(verifier):
    ingest = SimpleNamespace(checkpoint=AsyncMock(return_value=dict(revision=0, cursor={})), publish_page=AsyncMock())
    c = SimpleNamespace(ingest=ingest, fetch=AsyncMock(), execute=AsyncMock(side_effect=asyncio.CancelledError()))
    q = SimpleNamespace(plan=AsyncMock())
    resources = {'collector.tdx_listing_status': c, 'listing_status.query': q}
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=resources.__getitem__))
    before = q.plan, c.fetch, ingest.publish_page, verifier.USE_PROXY.get(), verifier.PROXY_FALLBACK.get()
    with pytest.raises(asyncio.CancelledError):
        await verifier.verify_scope(manager, {}, SimpleNamespace(months=['2001-06'], proxy_only=True), dict(results={}))
    assert before == (q.plan, c.fetch, ingest.publish_page, verifier.USE_PROXY.get(), verifier.PROXY_FALLBACK.get())


def test_capacity_exact_explain_and_analyze_only_after_real_identity_guard(verifier):
    tool = importlib.import_module('measure_listing_status')
    storage = tool.ListingStatusCapacityStorage(dict(host='test', port=13348, user='test'), {},
                                              'a'*32, 'b'*64, 'production')
    storage.server_uuid = 'test-instance'
    connection = Mock()
    connection.engine.url.database = storage.database
    raw = connection.connection.cursor.return_value
    raw.fetchone.return_value = ('test-instance', storage.database)
    statements = ['ANALYZE TABLE security_listing_event',
        *(p+q for p in ('EXPLAIN ', 'EXPLAIN ANALYZE ') for q in tool.CAPACITY_QUERIES.values())]
    for sql in statements:
        storage.guard(connection, None, sql, (), None, False)
    assert raw.execute.call_count == 9
    for sql in ('ANALYZE TABLE stock', 'EXPLAIN SELECT * FROM security_listing_event',
                'ANALYZE TABLE security_listing_event; DELETE FROM stock',
                'EXPLAIN SELECT * FROM empire.security_listing_event'):
        with pytest.raises(ValueError):
            storage.guard(connection, None, sql, (), None, False)
    raw.fetchone.return_value = ('production', storage.database)
    with pytest.raises(ValueError, match='实际实例'):
        storage.guard(connection, None, statements[0], (), None, False)


@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Actual owned SQL/Redis opt-in')
async def test_actual_guarded_complete_month_and_formal_proofs(verifier):
    import httpx
    from source_test_storage import PrivateStorage, read_server_uuid
    from source_verification import finish

    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from tests.prefetch_source import prefetch_http
    from tests.test_listing_status import row, source

    cfg = load_config()
    settings = json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf-8'))
    storage = PrivateStorage(settings, cfg['redis'], uuid4().hex, token_hex(32), read_server_uuid(cfg['mysql']))
    manager, cleanup = None, dict(cleanup={}, errors=[])
    try:
        storage.create_sql()
        await storage.create_redis()
        storage.seed([], [])
        private = copy.deepcopy(cfg)
        private['mysql'], private['redis']['namespace'] = storage.settings, storage.namespace
        manager = build_manager(private)
        await manager.start('pipeline.archive')
        await manager.start('collector.tdx_listing_status')
        c = manager.registry.get('collector.tdx_listing_status')
        def response(*args, **kwargs):
            day = json.loads(kwargs['content'])['Params'][2]
            values = [row(), row(label='恢复上市日', code='600625', market=1), row(code='832317', market=2)] if day == '2001-06-15' else []
            return httpx.Response(200, json=source(day, values))
        c.http = prefetch_http(request=AsyncMock(side_effect=response))
        report = dict(results={})
        await verifier.verify_scope(manager, {}, SimpleNamespace(months=['2001-06'], proxy_only=False), report)
        result = report['results']['listing_status']
        assert result['pipeline_verified'] and result['pending'] == 0 and result['acceptance_complete']
        assert result['months']['2001-06']['events'] == 2 and len(result['source_days']) == 30
        assert not result['strict_proxy_verified']
    finally:
        await finish(manager, storage, None, cleanup, Redactor([storage.owner]))
    assert not cleanup['errors'] and all(cleanup['cleanup'].values())
