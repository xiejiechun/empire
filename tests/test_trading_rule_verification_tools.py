"""Private-session guard, complete parameter/citation comparison and cancelled observers."""
import asyncio
import copy
import importlib
import json
import os
from pathlib import Path
from secrets import token_hex
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import httpx
import pytest


@pytest.fixture
def capacity(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('trading_rule_capacity')


def test_metadata_requires_actual_owned_session_and_exact_sql(capacity):
    storage = capacity.RuleCapacityStorage(dict(host='test', port=13348, user='test'), {}, 'a' * 32, 'b' * 64, 'production')
    storage.server_uuid = 'private'
    conn = Mock()
    conn.engine.url.database = storage.database
    raw = conn.connection.cursor.return_value
    allowed = ['ANALYZE TABLE trading_rule_value,trading_rule_citation', *('EXPLAIN ' + q for q in capacity.QUERIES.values())]
    for statement in allowed:
        raw.fetchone.return_value = ('private', storage.database)
        storage.guard(conn, None, statement, (), None, False)
        for identity in [('production', storage.database), ('private', 'empire')]:
            raw.fetchone.return_value = identity
            with pytest.raises(ValueError, match='实际实例'):
                storage.guard(conn, None, statement, (), None, False)
        raw.fetchone.return_value = ('private', storage.database)
        for params, many in [({'extra': 1}, False), ((), True)]:
            with pytest.raises(ValueError):
                storage.guard(conn, None, statement, params, None, many)
    for statement in ('ANALYZE TABLE stock', allowed[0] + '; DELETE FROM trading_rule_value',
                      'EXPLAIN SELECT * FROM empire.trading_rule_value', 'SELECT * FROM empire.trading_rule_citation'):
        with pytest.raises(ValueError):
            storage.guard(conn, None, statement, (), None, False)


def test_same_count_wrong_parameter_or_citation_fails(capacity):
    live = importlib.import_module('trading_rule_verification')
    from empire.features.trading_rules.dataset import canonical_payload
    from tests.test_trading_rules import sample
    expected = canonical_payload('tick_rules', sample('tick_rules'))
    for target, field in [('rows', 'number_value'), ('citations', 'excerpt')]:
        changed = copy.deepcopy(expected)
        changed[target][0][field] = 'different'
        with pytest.raises(ValueError, match='完整集合/内容'):
            live.equal_payload(expected, changed['rows'], changed['citations'])


async def test_cancel_restores_observers_and_shared_network_policy(capacity):
    live = importlib.import_module('trading_rule_verification')
    request, publish = AsyncMock(), AsyncMock()
    http = SimpleNamespace(request=request)
    ingest = SimpleNamespace(publish_page=publish)
    collector = SimpleNamespace(checkpoint_revision=AsyncMock(return_value=0), execute=AsyncMock(side_effect=asyncio.CancelledError()))
    resources = {'rules.source': SimpleNamespace(http=http), 'ingest.publish': ingest,
                 'collector.rules_limit_rules': collector, 'rules.limit_rules.query': Mock()}
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=resources.__getitem__))
    before = live.USE_PROXY.get(), live.PROXY_FALLBACK.get(), live.ROUTE_COUNTS.get()
    with pytest.raises(asyncio.CancelledError):
        await live.verify_scope(manager, {}, SimpleNamespace(proxy_only=True), dict(results={}))
    assert http.request is request and ingest.publish_page is publish
    assert before == (live.USE_PROXY.get(), live.PROXY_FALLBACK.get(), live.ROUTE_COUNTS.get())


@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='explicit owned SQL opt-in')
async def test_actual_owned_seven_kind_pipeline_and_cleanup(capacity):
    from source_test_storage import read_server_uuid, test_settings
    from source_verification import finish

    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from tests.prefetch_source import prefetch_http
    from tests.test_trading_rules import responses

    cfg = load_config()
    settings = json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf8'))
    storage = capacity.RuleCapacityStorage(test_settings(settings), cfg['redis'], uuid4().hex, token_hex(32), read_server_uuid(cfg['mysql']))
    manager = None
    report = dict(cleanup={}, errors=[])
    try:
        storage.create_sql()
        await storage.create_redis()
        storage.seed([], [])
        private = copy.deepcopy(cfg)
        private['mysql'], private['redis']['namespace'] = storage.settings, storage.namespace
        manager = build_manager(private)
        await manager.start('pipeline.archive')
        await manager.start('collector.rule_sources')
        docs = responses()
        async def response(method, url, **kwargs):
            return httpx.Response(200, content=docs[url], request=httpx.Request(method, url))
        manager.registry.get('rules.source').http = prefetch_http(request=AsyncMock(side_effect=response))
        live = importlib.import_module('trading_rule_verification')
        result = dict(results={})
        await live.verify_scope(manager, {}, SimpleNamespace(proxy_only=False), result)
        assert len(result['results']) == 7 and sum(r['rows'] for r in result['results'].values()) == 77
        assert len(result['responses']) == 15
        assert all(r['pipeline_verified'] and r['pending_stream'] == 0 and not r['strict_proxy_verified'] for r in result['results'].values())
        mysql = manager.registry.get('mysql.store')
        def inspect():
            with mysql.read_engine.connect() as conn:
                assert conn.exec_driver_sql('EXPLAIN ' + capacity.QUERIES['page']).first()
                for statement in ('SELECT * FROM empire.stock', 'ANALYZE TABLE stock'):
                    with pytest.raises(ValueError):
                        conn.exec_driver_sql(statement)
        await mysql.read(inspect)
    finally:
        await finish(manager, storage, None, report, Redactor([settings.get('password'), storage.owner]))
    assert not report['errors'] and all(report['cleanup'][k] for k in ('shutdown', 'sql', 'redis', 'sql_lock', 'connections'))
    assert report['remaining'] == dict(sql=False, redis=False)
