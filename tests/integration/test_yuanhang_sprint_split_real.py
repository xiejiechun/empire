"""Bounded source acceptance for the one project with separate maintenance rounds."""
import json
import os
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.yuanhang_limits.contract import SPLIT_POOL
from empire.features.yuanhang_limits.model import digest
from empire.features.yuanhang_limits.repository import decode_member
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1' or os.environ.get('EMPIRE_SPRINT_REAL') != '1',
    reason='Explicit bounded real-source proxy acceptance')]


async def test_single_owner_source_to_query_and_same_cutoff_zero_requests():
    manifest = json.loads(Path('build/sprint-split-sample-20261102.json').read_text(encoding='utf-8'))
    cfg = load_config()
    assert ':test:' in cfg['redis']['namespace'] and cfg['mysql']['database'].endswith('_test')
    manager, counts, expected, phases = build_manager(cfg), {}, {}, []
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts)
    selected = set(manifest['selected_dates'])
    report = {k: v for k, v in manifest.items() if k != 'calendar'}
    report.update(network_policy=dict(use_proxy=True, proxy_fallback=True), passed=False)
    try:
        await manager.start('collector.yuanhang_limits_sprint_limit_up')
        current = manager.registry.get('collector.yuanhang_limits_sprint_limit_up')
        query = manager.registry.get('yuanhang.limits.query')
        with query.mysql.engine.begin() as conn:
            rows = [dict(day=date.fromisoformat(day), flag=flag) for day, flag in manifest['calendar']]
            for offset in range(0, len(rows), 500):
                conn.execute(text('INSERT INTO trade_calendar VALUES (:day,:flag,NOW(6))'), rows[offset:offset + 500])
        original_plan = query.collection_plan

        async def sampled_plan(*args, **kwargs):
            plan = await original_plan(*args, **kwargs)
            units = [day for day in [*plan['units'], *plan.get('pending', [])] if day in selected]
            return {**plan, 'units': units, 'pending': [], 'remaining': 0}

        query.collection_plan = sampled_plan
        for collector in (current,):
            original_fetch = collector.fetch

            async def capture(day, *, reservation=None, original_fetch=original_fetch):
                unit, stamp = await original_fetch(day, reservation=reservation)
                expected[day] = unit
                return unit, stamp

            collector.fetch = capture
        for scope, fresh, label in (('recent', False, 'sample_initialization'),
                ('history', True, 'explicit_historical_audit'), ('recent', True, 'explicit_recent_recheck'),
                ('recent', False, 'recent_nochange'), ('history', False, 'history_nochange')):
            collector = current
            before = dict(counts)
            await collector.execute(fresh=fresh, baseline_revision=await collector.checkpoint_revision(), history_only=True, maintenance_scope=scope)
            phases.append(dict(label=label, project=collector.project_id,
                requests=collector.stats['requests'], response_bytes=collector.stats['response_bytes'],
                wire_bytes=collector.stats['wire_bytes'], queued_messages=collector.stats['queued_messages'],
                queued_bytes=collector.stats['queued_bytes'], units=collector.stats['completed_units'],
                routes={k: counts[k] - before.get(k, 0) for k in counts}))
        assert [p['units'] for p in phases] == [23, 22, 1, 0, 0]
        assert [p['requests'] for p in phases] == [23, 22, 1, 0, 0]
        for day in sorted(selected):
            rows, after = [], ''
            while True:
                result = await query.members(day, SPLIT_POOL, after=after)
                rows.extend(decode_member(row) for row in result['rows'])
                after = result['next']
                if after is None:
                    break
            assert rows == expected[day]['rows']
            assert (await query.audit_pool(day, SPLIT_POOL))['complete']
        store = manager.registry.get('redis.store')
        assert await store.client.xlen(store.stream) == 0
        assert counts.get('direct_requests', 0) == 0 and counts.get('proxy_requests', 0) >= 46
        writes = []

        def track(conn, cursor, statement, params, context, many):
            if statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) and 'yuanhang_limit_' in statement:
                writes.append(statement)

        event.listen(query.mysql.engine, 'before_cursor_execute', track)
        await current.execute(baseline_revision=await current.checkpoint_revision(), history_only=True)
        assert not writes and current.stats['requests'] == 0
        report.update(passed=True, phases=phases, routes=counts, pending=0,
            content_sha256={day: digest(unit) for day, unit in expected.items()},
            actual_sample_fraction=23 / 442, untested='其余419个日期本轮未实采；其他四池及原因不扩采。')
    finally:
        report.update(phases=phases, routes=counts)
        Path('build/sprint-single-real-20261102.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        await manager.shutdown()
        client = create_client(cfg['redis'])
        try:
            prefix = cfg['redis']['namespace'] + ':'
            keys = [key async for key in client.scan_iter(match=prefix + '*')]
            assert ':test:' in prefix and all(key.startswith(prefix) for key in keys)
            if keys:
                await client.delete(*keys)
        finally:
            await client.aclose()
            USE_PROXY.reset(tokens[0])
            PROXY_FALLBACK.reset(tokens[1])
            ROUTE_COUNTS.reset(tokens[2])
