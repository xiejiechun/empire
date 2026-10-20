"""Wrong-instance, set-content, cancellation and real private SQL positive checks."""
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

import httpx
import pytest


@pytest.fixture
def capacity(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / 'scripts'))
    return importlib.import_module('performance_capacity')


@pytest.mark.parametrize('table', ['earnings_forecast', 'earnings_quick', 'earnings_disclosure',
    'earnings_report', 'shareholder_count', 'shareholder_change'])
def test_guard_exact_statements_always_verify_actual_server(capacity, table):
    storage = capacity.PerformanceCapacityStorage(dict(host='test', port=13348, user='test'), {},
        'a'*32, 'b'*64, 'production')
    storage.server_uuid = 'private'
    conn = Mock()
    conn.engine.url.database = storage.database
    raw = conn.connection.cursor.return_value
    raw.fetchone.return_value = ('private', storage.database)
    explain = 'EXPLAIN SELECT * FROM '+table+' LIMIT 1'
    storage.explain_sql.add(explain)
    for sql in ['ANALYZE TABLE '+table, explain]:
        storage.guard(conn, None, sql, (), None, False)
        for actual in [('production', storage.database), ('private', 'empire')]:
            raw.fetchone.return_value = actual
            with pytest.raises(ValueError, match='实际实例'):
                storage.guard(conn, None, sql, (), None, False)
        raw.fetchone.return_value = ('private', storage.database)
    for sql in ['ANALYZE TABLE stock', 'EXPLAIN SELECT * FROM stock', explain+'; DELETE FROM stock']:
        with pytest.raises(ValueError):
            storage.guard(conn, None, sql, (), None, False)
    storage.explain_sql.add('EXPLAIN SELECT * FROM empire.stock')
    with pytest.raises(ValueError):
        storage.guard(conn, None, 'EXPLAIN SELECT * FROM empire.stock', (), None, False)


def test_same_count_different_set_and_content_fail(capacity):
    live = importlib.import_module('performance_verification')
    from empire.features.performance.contract import FIELDS
    from tests.test_tdx_performance import source
    for kind in FIELDS:
        if kind == 'shareholder_changes':
            continue
        from empire.features.performance.source import parse
        rows, _ = parse(kind, source(kind), '2026-06-30' if kind != 'holder_count' else None)
        changed = [dict(r) for r in rows]
        changed[0]['name'] = 'changed'
        with pytest.raises(ValueError, match='完整集合'):
            live.equal_rows(kind, rows, changed)
        changed[0] = {**rows[0], 'unified_code': '999999.SH'}
        with pytest.raises(ValueError, match='完整集合'):
            live.equal_rows(kind, rows, changed)


def test_formal_audit_hint_is_exact_and_does_not_hide_sql(capacity):
    from performance_storage import PerformanceStorage
    storage = PerformanceStorage(dict(host='test', port=13348, user='test'), {}, 'a'*32, 'b'*64, 'production')
    storage.server_uuid = 'private'
    conn = Mock()
    conn.engine.url.database = storage.database
    conn.connection.cursor.return_value.fetchone.return_value = ('private', storage.database)
    sql = 'SELECT /*+ MAX_EXECUTION_TIME(15000) */ * FROM earnings_report WHERE report_date=%(day)s ORDER BY record_key LIMIT 80001'
    storage.guard(conn, None, sql, (), None, False)
    for changed in [sql.replace('15000', '15001'), sql.replace('earnings_report', 'empire.earnings_report'),
                    sql + '; DELETE FROM stock', sql.replace('*/', 'DELETE FROM stock */'),
                    sql.replace('/*+', '/*!'), sql + ' /* SELECT * FROM empire.stock */']:
        with pytest.raises(ValueError):
            storage.guard(conn, None, changed, (), None, False)
    conn.connection.cursor.return_value.fetchone.return_value = ('production', storage.database)
    with pytest.raises(ValueError, match='实际实例'):
        storage.guard(conn, None, sql, (), None, False)


@pytest.mark.parametrize('kind', ['earnings_report', 'holder_count', 'shareholder_changes'])
async def test_cancel_restores_process_scope_and_hooks(capacity, kind):
    live = importlib.import_module('performance_verification')
    from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
    http = SimpleNamespace(request=AsyncMock())
    ingest = SimpleNamespace(publish_page=AsyncMock())
    c = SimpleNamespace(http=http, ingest=ingest, fetch=AsyncMock(side_effect=asyncio.CancelledError()),
        execute=AsyncMock(side_effect=asyncio.CancelledError()), checkpoint_revision=AsyncMock(return_value=0))
    manager = SimpleNamespace(start=AsyncMock(), entries={'collector.tdx_'+kind: SimpleNamespace(plugin=c)}, registry=Mock())
    before = (http.request, c.fetch, ingest.publish_page, live.runtime.quarterly_plan,
        USE_PROXY.get(), PROXY_FALLBACK.get(), ROUTE_COUNTS.get())
    args = SimpleNamespace(proxy_only=True, periods=['2022-03-31'], months=['2014-06-01'])
    with pytest.raises(asyncio.CancelledError):
        await live.verify_kind(manager, kind, dict(selected=[]), args, {})
    assert before == (http.request, c.fetch, ingest.publish_page, live.runtime.quarterly_plan,
        USE_PROXY.get(), PROXY_FALLBACK.get(), ROUTE_COUNTS.get())


@pytest.mark.skipif(os.environ.get('EMPIRE_INTEGRATION') != '1', reason='explicit independent SQL opt-in')
async def test_six_kind_real_owned_sql_positive(capacity):
    from performance_storage import PerformanceStorage
    from source_test_storage import read_server_uuid, test_settings
    from source_verification import finish

    from empire.core.config import load_config
    from empire.core.redaction import Redactor
    from empire.features.performance.collector import PerformanceCollector
    from empire.features.performance.contract import UNIT_KINDS
    from empire.features.performance.dataset import PerformanceDataset, decode, read_unit
    from empire.features.performance.source import parse
    from empire.plugins.infra.mysql_store import make_engine
    from tests.test_tdx_performance import source
    from tests.test_tdx_shareholder_changes import source as changes_source

    cfg = load_config()
    raw = json.loads(Path(os.environ['EMPIRE_TEST_MYSQL_SETTINGS']).read_text('utf8'))
    storage = PerformanceStorage(test_settings(raw), cfg['redis'], uuid4().hex, token_hex(32), read_server_uuid(cfg['mysql']))
    report = dict(cleanup={}, errors=[])
    engine = manager = None
    try:
        storage.create_sql()
        await storage.create_redis()
        storage.seed([], [])
        engine = make_engine(storage.settings)
        for kind in UNIT_KINDS:
            period = '2025-08-01' if kind == 'shareholder_changes' else '2026-06-30'
            body = changes_source() if kind == 'shareholder_changes' else source(kind)
            rows, _ = parse(kind, body, period if kind != 'holder_count' else None)
            unit = '000001.SZ' if kind == 'holder_count' else period+'|SZ'
            rows = [r for r in rows if r['unified_code'] == '000001.SZ']
            c, mapping = PerformanceCollector(kind), PerformanceDataset(kind)
            envelope = c.envelope(unit, rows, 1, 'sql-smoke', datetime.now(UTC))
            data = {**mapping.normalize(envelope), 'archive_state': {}}
            with engine.begin() as conn:
                result = mapping.write(conn, envelope, data)
                assert result['row_count'] == len(rows)
                actual = [decode(kind, r) for r in read_unit(conn, kind, unit)]
                assert actual == rows
        from empire.bootstrap import build_manager
        from tests.test_tdx_performance import directory
        private = copy.deepcopy(cfg)
        private['mysql'], private['redis']['namespace'] = storage.settings, storage.namespace
        manager = build_manager(private)
        await manager.start('infra.http')
        http = manager.registry.get('http.fetch')
        current = {}
        async def response(method, url, **kwargs):
            kind = current['kind']
            params = json.loads(kwargs['content'])['Params']
            if 'cache' in url:
                body = directory(kind)
            elif kind == 'shareholder_changes':
                body = changes_source()
            else:
                security = params[1] if kind == 'holder_count' else ''
                body = source(kind, security=security)
            return httpx.Response(200, json=body)
        http.request = AsyncMock(side_effect=response)
        live = importlib.import_module('performance_verification')
        await manager.start('pipeline.archive')
        for kind in UNIT_KINDS:
            current['kind'] = kind
            result = {}
            await live.verify_kind(manager, kind, dict(selected=[dict(unified_code='000001.SZ')]),
                SimpleNamespace(proxy_only=False, periods=['2026-06-30'], months=['2025-08-01']), result)
            assert result['pipeline_verified'] and result['acceptance_complete'] and result['pending_stream'] == 0
            assert not result['strict_proxy_verified']  # Synthetic HTTP never proves proxy source acceptance.
            assert not any('测试业务' in item['measured'] for item in result['preparation'])
    finally:
        if engine:
            engine.dispose()
        await finish(manager, storage, None, report, Redactor([raw.get('password'), storage.owner]))
    assert not report['errors'] and all(report['cleanup'].get(k) is True for k in ['shutdown','sql','redis','sql_lock','connections'])
    assert report['remaining'] == dict(sql=False, redis=False)
