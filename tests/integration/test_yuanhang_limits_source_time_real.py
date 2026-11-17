"""One complete live pool through shared download, volatile publish and replay."""
import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.yuanhang_limits.intraday import collect_live
from empire.features.yuanhang_limits.model import digest
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1' or os.environ.get('EMPIRE_POOL_TIME_REAL') != '1',
    reason='Explicit complete live-pool source-time acceptance')]


async def test_complete_pool_time_validation_replays_without_sql_writes():
    cfg = load_config()
    assert ':test:' in cfg['redis']['namespace'] and cfg['mysql']['database'].endswith('_test')
    manager, counts, dml, expected = build_manager(cfg), {}, [], []
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts)
    mysql = None

    def track(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')):
            dml.append(statement.split()[0])

    try:
        await manager.start('collector.yuanhang_limits_limit_up_pool')
        collector = manager.registry.get('collector.yuanhang_limits_limit_up_pool')
        mysql = manager.registry.get('mysql.store')
        redis = manager.registry.get('redis.store')
        query = manager.registry.get('yuanhang.limits.query')
        event.listen(mysql.engine, 'before_cursor_execute', track)
        event.listen(mysql.archive_engine, 'before_cursor_execute', track)
        fetch = collector.fetch

        async def capture(key, **kwargs):
            result = await fetch(key, **kwargs)
            expected.append(result[0])
            return result

        collector.fetch = capture
        now = datetime.now(CHINA)
        result = await collect_live(collector, now)
        assert result['storage'] == 'redis_only' and result['queued_messages'] == 0
        stored = await collector.live_store.read(collector.pool, now.date().isoformat())
        assert stored['unit'] == expected[0]
        actual, after = [], None
        while True:
            batch = await query.browse((3, collector.pool, '', now.date().isoformat(), '', ''), after)
            actual.extend(batch['rows'])
            after = batch['next']
            if after is None:
                break
        assert {r['unified_code'] for r in actual} == {r['unified_code'] for r in expected[0]['rows']}
        assert len(actual) == expected[0]['source_total']
        assert not dml and await redis.client.xlen(redis.stream) == 0
        for table in ('yuanhang_limit_pool', 'yuanhang_limit_member', 'yuanhang_limit_reason', 'collection_state'):
            assert await query.read(lambda conn, table=table:
                conn.execute(text('SELECT COUNT(*) FROM ' + table)).scalar_one()) == 0
        root = Path(__file__).resolve().parents[2]
        paths = ['src/empire/features/yuanhang_limits/' + name + '.py'
                 for name in ('model', 'source', 'collector', 'intraday', 'intraday_store', 'intraday_query')]
        report = dict(passed=True, at=now.isoformat(), pool=collector.pool,
            scope='one complete current-date pool; earlier failed responses unavailable',
            network_policy=dict(use_proxy=True, proxy_fallback=True), routes=counts,
            source_total=len(actual), content_sha256=digest(expected[0]),
            requests=collector.stats['requests'], response_bytes=collector.stats['response_bytes'],
            archive_messages=0, sql_business_dml=0, exact_content_and_key_set_verified=True,
            bindings={p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths})
    finally:
        if mysql is not None:
            event.remove(mysql.engine, 'before_cursor_execute', track)
            event.remove(mysql.archive_engine, 'before_cursor_execute', track)
        await manager.shutdown()
        client = create_client(cfg['redis'])
        prefix = cfg['redis']['namespace'] + ':'
        keys = [key async for key in client.scan_iter(match=prefix + '*')]
        assert ':test:' in prefix and all(key.startswith(prefix) for key in keys)
        if keys:
            await client.delete(*keys)
        await client.aclose()
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])
    if os.environ.get('EMPIRE_POOL_TIME_REPORT'):
        Path(os.environ['EMPIRE_POOL_TIME_REPORT']).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
