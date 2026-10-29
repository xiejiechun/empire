"""Live proxies into private Redis; prove no intraday SQL/archive side effects."""
import hashlib
import json
import os
import random
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.time import CHINA
from empire.features.yuanhang_limits.contract import POOLS
from empire.features.yuanhang_limits.intraday import collect_live
from empire.features.yuanhang_limits.model import digest
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1' or os.environ.get('EMPIRE_INTRADAY_REAL') != '1',
    reason='Explicit real proxy intraday acceptance')]


async def test_five_pools_redis_replay_without_archive_or_business_dml():
    cfg = load_config()
    assert ':test:' in cfg['redis']['namespace'] and cfg['mysql']['database'].endswith('_test')
    manager, counts, expected, report, dml = build_manager(cfg), {}, {}, {}, []
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False), ROUTE_COUNTS.set(counts)
    mysql = None

    def track(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'REPLACE')):
            dml.append(statement.split()[0])

    try:
        await manager.start('collector.yuanhang_limits_limit_up_pool')
        mysql = manager.registry.get('mysql.store')
        event.listen(mysql.engine, 'before_cursor_execute', track)
        q = manager.registry.get('yuanhang.limits.query')
        redis = manager.registry.get('redis.store')
        now = datetime.now(CHINA)
        day = now.date().isoformat()
        pools, securities = [], set()
        for pool in POOLS:
            await manager.start('collector.yuanhang_limits_' + pool)
            c = manager.registry.get('collector.yuanhang_limits_' + pool)
            original = c.fetch

            async def capture(key, *, reservation=None, fetch=original, owner=pool):
                unit, observed = await fetch(key, reservation=reservation)
                expected[owner] = unit
                return unit, observed

            c.fetch = capture
            result = await collect_live(c, now)
            assert result['storage'] == 'redis_only' and result['queued_messages'] == 0
            stored = await c.live_store.read(pool, day)
            assert stored['unit'] == expected[pool]
            actual, after = [], None
            while True:
                page = await q.browse((3, pool, '', day, '', ''), after)
                actual.extend(page['rows'])
                after = page['next']
                if after is None:
                    break
            assert {r['unified_code'] for r in actual} == {r['unified_code'] for r in expected[pool]['rows']}
            securities.update(r['unified_code'] for r in actual)
            body_keys = [c.live_store.body_key(pool, version)
                         for version in await redis.client.zrange(c.live_store.keys(pool)[1], 0, -1)]
            keys = body_keys + c.live_store.keys(pool)[1:]
            memory = sum([(await redis.client.memory_usage(key)) or 0 for key in keys])
            pools.append(dict(pool=pool, total=len(actual), digest=digest(expected[pool]),
                requests=c.stats['requests'], wire_bytes=c.stats['wire_bytes'],
                response_bytes=c.stats['response_bytes'], redis_memory_bytes=memory,
                packed_bytes=int(await redis.client.hget(c.live_store.keys(pool)[2], 'bytes')),
                consistency=stored['consistency']))
        assert len(securities) >= 30
        sample = random.Random(20261027).sample(sorted(securities), 30)
        assert not dml and await redis.client.xlen(redis.stream) == 0
        assert counts.get('proxy_requests', 0) >= 5 and not counts.get('direct_requests', 0)
        for table in ('yuanhang_limit_pool', 'yuanhang_limit_member', 'yuanhang_limit_reason', 'collection_state'):
            assert await q.read(lambda conn, table=table: conn.execute(text('SELECT COUNT(*) FROM ' + table)).scalar_one()) == 0
        root = Path(__file__).resolve().parents[2]
        paths = list((root / 'src/empire/features/yuanhang_limits').glob('*.py'))
        paths.append(root / 'src/empire/plugins/pipeline/ingest.py')
        report = dict(passed=True, at=now.isoformat(), pools=pools, routes=counts,
            seed=20261027, sample_pool=len(securities), sample=sample, sample_pool_sha256=digest(sorted(securities)),
            sample_content_verified=True, archive_messages=0, business_dml=0,
            scope='Real shared proxies/prefetch -> guarded volatile publication -> isolated Redis -> official replay query; session boundaries separately tested.',
            bindings={p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths})
    finally:
        if mysql is not None:
            event.remove(mysql.engine, 'before_cursor_execute', track)
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
    if os.environ.get('EMPIRE_INTRADAY_REPORT'):
        Path(os.environ['EMPIRE_INTRADAY_REPORT']).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
