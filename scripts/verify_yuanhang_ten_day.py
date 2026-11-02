"""Bounded production acceptance through shared proxy, ingestion and formal queries."""
import argparse
import asyncio
import hashlib
import json
import math
import random
from datetime import datetime
from pathlib import Path

from release import require_stopped
from release_lock import ReleaseLock
from sqlalchemy import text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.features.yuanhang_limits.model import digest
from empire.features.yuanhang_limits.repository import decode_member
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


async def verify(args):
    manager = build_manager(load_config(args.config))
    routes = {}
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(routes)
    report = dict(started=datetime.now().isoformat(), seed=20261102, passed=False,
                  network_policy=dict(use_proxy=True, proxy_fallback=True), samples=[])
    try:
        await manager.start('collector.yuanhang_limits_limit_up_pool')
        q = manager.registry.get('yuanhang.limits.query')
        original_plan = q.collection_plan
        plan = await original_plan('limit_up_pool', force=True, scope='recent')
        days, cutoff = sorted(plan['units']), plan['cutoff']
        assert len(days) == 10
        report['pool_population_units'] = 5 * len(days)
        samples = [('limit_up_pool', [days[-1]]), ('sprint_limit_up', [days[-2]]),
                   ('open_limit_up_pool', [days[0]])]
        def reason_keys(conn):
            return [[r[0].isoformat(), r[1]] for r in conn.execute(text(
                'SELECT trade_date,unified_code FROM ('
                'SELECT trade_date,unified_code FROM yuanhang_limit_member WHERE trade_date BETWEEN :first AND :last '
                'UNION SELECT trade_date,unified_code FROM yuanhang_limit_reason WHERE trade_date BETWEEN :first AND :last'
                ') u ORDER BY trade_date DESC,unified_code LIMIT 100001'), dict(first=days[0], last=cutoff))]
        keys = await q.read(reason_keys)
        assert 0 < len(keys) <= 100000
        report['reason_population_units'] = len(keys)
        selected = random.Random(report['seed']).sample(keys, max(1, math.ceil(len(keys) * .05)))
        selected.sort(key=lambda key: (-int(key[0].replace('-', '')), key[1]))
        samples.append(('reason', selected))
        for pool, selected in samples:
            await manager.start('collector.yuanhang_limits_' + pool)
            c = manager.registry.get('collector.yuanhang_limits_' + pool)
            expected = {}
            fetch = c.fetch
            async def capture(key, *, reservation=None, fetch=fetch):
                unit, observed = await fetch(key, reservation=reservation)
                identity = tuple(key) if isinstance(key, list) else key
                expected[identity] = unit
                return unit, observed
            async def bounded(kind, *, exclude=(), scan_after=None, **kwargs):
                assert kind == pool
                units = list(selected)
                if scan_after:
                    _, day, code = scan_after
                    units = [k for k in units if k[0] < day or k[0] == day and k[1] > code]
                units = [k for k in units if (tuple(k) if isinstance(k, list) else k) not in exclude]
                result = dict(units=units[:256], cutoff=cutoff, remaining=0 if len(units) <= 256 else None)
                if len(units) > 256:
                    result['scan_after'] = [0, *units[255]]
                return result
            c.fetch, q.collection_plan = capture, bounded
            result = await c.execute(baseline_revision=await c.checkpoint_revision(),
                                     history_only=True, maintenance_scope='recent')
            q.collection_plan = original_plan
            assert len(expected) == len(selected)
            for key, unit in expected.items():
                if pool == 'reason':
                    stored = await q.reason(*key)
                    assert stored and stored['content_sha256'] == digest(unit)
                    assert {k: stored[k].isoformat() if k == 'trade_date' else stored[k] for k in unit} == unit
                else:
                    rows, after = [], ''
                    while True:
                        page = await q.members(key, pool, after=after)
                        rows.extend(decode_member(row) for row in page['rows'])
                        after = page['next']
                        if after is None:
                            break
                    assert rows == unit['rows'] and (await q.audit_pool(key, pool))['complete']
            confirmation = await c.confirmation.page_status('ths_yuanhang', c.job_key,
                c.project_id, result['batch_id'], result['page'])
            assert confirmation['status'] == 'complete'
            report['samples'].append(dict(pool=pool, units=selected, matched=len(expected),
                contents={str(k): digest(v) for k, v in expected.items()}, stats=dict(c.stats),
                batch_id=result['batch_id'], confirmed_page=result['page'], confirmation=confirmation))
            c.fetch = fetch
        report.update(passed=True, routes=routes, finished=datetime.now().isoformat())
    finally:
        await manager.shutdown()
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])
        paths = list(Path('src/empire/features/yuanhang_limits').glob('*.py')) + [Path(__file__)]
        report['bindings'] = {p.as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print('PASS bounded pools and reasons: source sets/content match formal query; batches confirmed and cleared')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='dist/EmpireDesktop/config.toml')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    with ReleaseLock(root) as lock:
        require_stopped(lock, root)
        asyncio.run(verify(args))
