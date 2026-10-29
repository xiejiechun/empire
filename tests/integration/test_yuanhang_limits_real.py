"""Explicit live-source acceptance; private SQL/Redis fixture owns all writes."""
import asyncio
import hashlib
import json
import os
import random
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.yuanhang_limits.contract import POOLS
from empire.features.yuanhang_limits.model import digest
from empire.features.yuanhang_limits.repository import decode_member
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1' or os.environ.get('EMPIRE_LIMIT_REAL') != '1',
    reason='Explicit live-source proxy acceptance opt-in')]


async def test_five_whole_pools_and_random30_distinct_reason_stocks():
    cfg = load_config()
    assert ':test:' in cfg['redis']['namespace'] and cfg['mysql']['database'].endswith('_test')
    manager, counts, report, expected = build_manager(cfg), {}, {}, {}
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False), ROUTE_COUNTS.set(counts)
    day = '2024-10-08'
    report.update(day=day, seed=20261026, routes=counts, pool_results={}, earliest_probe={},
                  network_policy=dict(use_proxy=True, proxy_fallback=False), pending=None, passed=False)
    try:
        securities = set()
        for pool in POOLS:
            capability = 'collector.yuanhang_limits_' + pool
            await manager.start(capability)
            c = manager.registry.get(capability)
            q = manager.registry.get('yuanhang.limits.query')
            days = [day, '1990-12-19', *(['2020-02-03'] if pool == 'limit_down_pool' else [])]
            q.collection_plan = AsyncMock(return_value=dict(units=days, cutoff=day, remaining=0))
            original = c.fetch

            async def capture(key, *, reservation=None, fetch=original, kind=pool):
                unit, stamp = await fetch(key, reservation=reservation)
                expected[(kind, unit['trade_date'])] = unit
                return unit, stamp

            c.fetch = capture
            await asyncio.wait_for(c.execute(history_only=True), 180)
            rows, after = [], ''
            while True:
                result = await q.members(day, pool, after=after)
                rows.extend(decode_member(r) for r in result['rows'])
                after = result['next']
                if after is None:
                    break
            assert rows == expected[(pool, day)]['rows']
            assert (await q.audit_pool(day, pool))['complete']
            securities.update(r['unified_code'] for r in rows)
            report['pool_results'][pool] = dict(count=len(rows), content_sha256=digest(rows),
                requests=c.stats['requests'], response_bytes=c.stats['response_bytes'],
                wire_bytes=c.stats['wire_bytes'], queued_bytes=c.stats['queued_bytes'])
            early_rows, early_cursor = [], ''
            while True:
                result = await q.members('1990-12-19', pool, after=early_cursor)
                early_rows.extend(decode_member(r) for r in result['rows'])
                early_cursor = result['next']
                if early_cursor is None:
                    break
            assert early_rows == expected[(pool, '1990-12-19')]['rows']
            assert (await q.audit_pool('1990-12-19', pool))['complete']
            report['earliest_probe'][pool] = dict(day='1990-12-19', count=len(early_rows), digest=digest(early_rows))
            if pool == 'limit_down_pool':
                fixed_rows, cursor = [], ''
                while True:
                    result = await q.members('2020-02-03', pool, after=cursor)
                    fixed_rows.extend(decode_member(r) for r in result['rows'])
                    cursor = result['next']
                    if cursor is None:
                        break
                assert fixed_rows == expected[(pool, '2020-02-03')]['rows']
                assert len(fixed_rows) == 2983
                assert next(r for r in fixed_rows if r['unified_code'] == '300362.SZ')['source_market_id'] is None
                report['fixed_large_history'] = dict(day='2020-02-03', pool=pool, count=len(fixed_rows), digest=digest(fixed_rows))
        report['fixed_history_regressions'] = []
        for fixed_pool, fixed_day in [('limit_up_pool', '2020-02-05'), ('open_limit_up_pool', '2022-09-20'),
                                      ('limit_down_pool', '2021-01-14'), ('limit_up_pool', '2023-11-03')]:
            fixed = manager.registry.get('collector.yuanhang_limits_' + fixed_pool)
            q.collection_plan.return_value = dict(units=[fixed_day], cutoff=day, remaining=0)
            await asyncio.wait_for(fixed.execute(baseline_revision=await fixed.checkpoint_revision(), history_only=True), 180)
            rows, after = [], ''
            while True:
                result = await q.members(fixed_day, fixed_pool, after=after)
                rows.extend(decode_member(r) for r in result['rows'])
                after = result['next']
                if after is None:
                    break
            assert rows == expected[(fixed_pool, fixed_day)]['rows']
            assert (await q.audit_pool(fixed_day, fixed_pool))['complete']
            if fixed_day == '2023-11-03':
                special = next(r for r in rows if r['unified_code'] == '871478.BJ')
                assert special['source_market_id'] == 151 and special['identity_basis'] == 'market_id'
            elif fixed_pool == 'limit_up_pool':
                special = next(r for r in rows if r['unified_code'] == '300362.SZ')
                assert special['identity_basis'] == 'pool_history' and special['source_market_id'] is None
            elif fixed_pool == 'open_limit_up_pool':
                assert any(r['first_limit_up_time'] == 0 for r in rows)
            else:
                special = next(r for r in rows if r['unified_code'] == '600687.SH')
                assert special['identity_basis'] == 'sina_lookup' and special['source_market_id'] is None
            report['fixed_history_regressions'].append(dict(pool=fixed_pool, day=fixed_day,
                count=len(rows), digest=digest(rows)))
        candidates = sorted(securities)
        sample = random.Random(report['seed']).sample(candidates, 30)
        report.update(sample_pool_size=len(candidates), sample_pool_sha256=digest(candidates), sample=sample)
        await manager.start('collector.yuanhang_limits_reason')
        c = manager.registry.get('collector.yuanhang_limits_reason')
        fixed_reasons = [['2026-07-15', '688192.SH'], ['2026-07-13', '688192.SH'],
                         ['2026-10-19', '002748.SZ'], ['2026-10-19', '002917.SZ'],
                         ['2026-10-19', '600167.SH'], ['2020-08-03', '300114.SZ']]
        q.collection_plan.return_value = dict(units=[[day, code] for code in sample] + fixed_reasons, cutoff=day, remaining=0)
        original = c.fetch

        async def capture_reason(key, *, reservation=None):
            unit, stamp = await original(key, reservation=reservation)
            expected[(unit['trade_date'], unit['unified_code'])] = unit
            return unit, stamp

        c.fetch = capture_reason
        await asyncio.wait_for(c.execute(history_only=True), 240)
        reasons = []
        for code in sample:
            result = await q.reason(day, code)
            assert result is not None
            canonical = {k: result[k].isoformat() if k == 'trade_date' else result[k] for k in expected[(day, code)]}
            assert canonical == expected[(day, code)]
            reasons.append(dict(code=code, availability=result['availability'], content_sha256=digest(canonical)))
        for fixed_day, fixed_code in fixed_reasons:
            result = await q.reason(fixed_day, fixed_code)
            canonical = {k: result[k].isoformat() if k == 'trade_date' else result[k]
                         for k in expected[(fixed_day, fixed_code)]}
            assert canonical == expected[(fixed_day, fixed_code)]
        store = manager.registry.get('redis.store')
        report.update(reason_results=reasons, reason_requests=c.stats['requests'],
                      reason_response_bytes=c.stats['response_bytes'], reason_wire_bytes=c.stats['wire_bytes'],
                      fixed_reasons=fixed_reasons, pending=await store.client.xlen(store.stream))
        assert report['pending'] == 0
        assert counts.get('proxy_requests', 0) >= 56 and counts.get('direct_requests', 0) == 0
        report['passed'] = True
    finally:
        await manager.shutdown()
        client = create_client(cfg['redis'])
        prefix = cfg['redis']['namespace'] + ':'
        keys = [key async for key in client.scan_iter(match=prefix + '*')]
        assert ':test:' in prefix and all(key.startswith(prefix) for key in keys)
        if keys:
            await client.delete(*keys)
        await client.aclose()
        for variable, token in zip((USE_PROXY, PROXY_FALLBACK, ROUTE_COUNTS), tokens):
            variable.reset(token)
        paths = [*Path('src/empire/features/yuanhang_limits').glob('*.py'), Path('src/empire/sources/security_identity.py')]
        report['bindings'] = {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        Path(os.environ.get('EMPIRE_LIMIT_REPORT', 'build/yuanhang-limits-real-20261026.json')).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
