"""BSE exact SQL guard, complete-set verification, cancellation and owned SQL smoke."""
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

import pytest


@pytest.fixture
def capacity(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'scripts'))
    return importlib.import_module('measure_bse_capacity')


def test_exact_bse_explain_analyze_require_real_session_identity(capacity):
    storage = capacity.BseCapacityStorage(dict(host='test', port=13348, user='test'), {},
                                         'a'*32, 'b'*64, 'production')
    storage.server_uuid = 'private'
    conn = Mock()
    conn.engine.url.database = storage.database
    raw = conn.connection.cursor.return_value
    raw.fetchone.return_value = ('private', storage.database)
    for sql in (capacity.EXPLAIN_SQL, capacity.ANALYZE_SQL):
        storage.guard(conn, None, sql, (), None, False)
    assert raw.execute.call_count == 2
    for sql in ('EXPLAIN SELECT * FROM stock', 'ANALYZE TABLE stock',
                capacity.ANALYZE_SQL+'; DELETE FROM security_code_alias',
                capacity.EXPLAIN_SQL.replace('security_code_alias', 'empire.security_code_alias'),
                'EXPLAIN ANALYZE SELECT * FROM security_code_alias'):
        with pytest.raises(ValueError):
            storage.guard(conn, None, sql, (), None, False)
    for identity in [('production', storage.database), ('private', 'empire')]:
        raw.fetchone.return_value = identity
        for sql in (capacity.EXPLAIN_SQL, capacity.ANALYZE_SQL):
            with pytest.raises(ValueError, match='实际实例'):
                storage.guard(conn, None, sql, (), None, False)


@pytest.mark.parametrize('many,params', [(True, ()), (False, {'other': 1})])
def test_special_statements_never_accept_batch_or_parameter_substitution(capacity, many, params):
    storage = capacity.BseCapacityStorage(dict(host='test', port=13348, user='test'), {},
                                         'a'*32, 'b'*64, 'production')
    conn = Mock()
    conn.engine.url.database = storage.database
    storage.server_uuid = 'private'
    conn.connection.cursor.return_value.fetchone.return_value = ('private', storage.database)
    with pytest.raises(ValueError):
        storage.guard(conn, None, capacity.EXPLAIN_SQL, params, None, many)


async def test_cancellation_restores_shared_network_policy(capacity):
    live = importlib.import_module('verify_bse_code_mapping')
    http = SimpleNamespace(request=AsyncMock(side_effect=asyncio.CancelledError()), response_policy=Mock())
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=lambda key: http))
    before = live.USE_PROXY.get(), live.PROXY_FALLBACK.get(), live.ROUTE_COUNTS.get()
    with pytest.raises(asyncio.CancelledError):
        await live.verify_scope(manager, {}, SimpleNamespace(proxy_only=True), dict(results={}))
    assert before == (live.USE_PROXY.get(), live.PROXY_FALLBACK.get(), live.ROUTE_COUNTS.get())


async def test_equal_count_wrong_sql_content_fails_and_response_released(capacity, monkeypatch):
    live = importlib.import_module('verify_bse_code_mapping')
    from tests.test_bse_code_mapping import ROWS, document
    response = SimpleNamespace(content=document(), close=Mock())
    http = SimpleNamespace(request=AsyncMock(return_value=response), response_policy=Mock())
    wrong = [{**ROWS[0], 'name': '相同数量但内容不同'}]
    mysql = SimpleNamespace(read=AsyncMock(return_value=wrong))
    resources = {'http.fetch': http, 'mysql.store': mysql}
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=resources.__getitem__))
    monkeypatch.setattr(live, 'publish', AsyncMock())
    with pytest.raises(ValueError, match='完整集合或内容'):
        await live.verify_scope(manager, {}, SimpleNamespace(proxy_only=True), dict(results={}))
    response.close.assert_called_once()
    live.publish.assert_awaited_once()


async def test_parse_failure_does_not_publish_and_releases_response(capacity, monkeypatch):
    live = importlib.import_module('verify_bse_code_mapping')
    response = SimpleNamespace(content=b'<table>incomplete', close=Mock())
    http = SimpleNamespace(request=AsyncMock(return_value=response), response_policy=Mock())
    manager = SimpleNamespace(start=AsyncMock(), registry=SimpleNamespace(get=lambda key: http))
    monkeypatch.setattr(live, 'publish', AsyncMock())
    with pytest.raises(ValueError):
        await live.verify_scope(manager, {}, SimpleNamespace(proxy_only=True), dict(results={}))
    live.publish.assert_not_awaited()
    response.close.assert_called_once()


@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Actual owned SQL/Redis opt-in')
async def test_actual_bse_guard_pipeline_and_cleanup(capacity):
    from source_verification import finish
    from sqlalchemy import text

    from empire.__main__ import acquire_instance_lock
    from empire.bootstrap import build_manager
    from empire.core.config import load_config
    from empire.core.redaction import Redactor

    cfg = load_config()
    settings = json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf-8'))
    storage = capacity.BseCapacityStorage(settings, cfg['redis'], uuid4().hex, token_hex(32),
                                         capacity.read_server_uuid(cfg['mysql']))
    manager, lock, cleanup = None, None, dict(cleanup={}, errors=[])
    try:
        lock = acquire_instance_lock()
        storage.create_sql()
        await storage.create_redis()
        storage.seed([], [])
        private = copy.deepcopy(cfg)
        private['mysql'], private['redis']['namespace'] = storage.settings, storage.namespace
        manager = build_manager(private)
        await manager.start('pipeline.ingest')
        rows = capacity.fixed_rows()
        await capacity.publish(manager, capacity.make_event(rows))
        mysql = manager.registry.get('mysql.store')
        assert await mysql.read(capacity.read_rows, mysql) == rows
        metadata = await mysql.control(capacity.inspect, mysql, storage.database)
        assert metadata['explain'][0]['key'] == 'ux_alias_security'
        assert await storage.client.xlen(manager.registry.get('redis.store').stream) == 0
        def rejected(sql):
            with mysql.engine.connect() as conn:
                return conn.execute(text(sql)).all()
        for sql in ('EXPLAIN SELECT * FROM stock', 'ANALYZE TABLE stock',
                    capacity.ANALYZE_SQL+'; DELETE FROM stock', 'SELECT * FROM empire.stock'):
            with pytest.raises(ValueError):
                await mysql.control(rejected, sql)
    finally:
        await finish(manager, storage, lock, cleanup, Redactor([storage.owner]))
    assert not cleanup['errors'] and all(cleanup['cleanup'].values())
    assert cleanup['remaining'] == dict(sql=False, redis=False)
