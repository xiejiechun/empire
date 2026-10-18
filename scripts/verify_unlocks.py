"""Real explicit range using the registered shared collector, archive and query."""
import argparse
import asyncio
import calendar
import json
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.unlocks import digest
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore


async def run(args):
    cfg, lock = load_config(args.config), acquire_instance_lock()
    manager, counts = build_manager(cfg), {}
    USE_PROXY.set(True)
    PROXY_FALLBACK.set(True)
    ROUTE_COUNTS.set(counts)
    report = dict(checked_at=datetime.now(UTC).isoformat(), policy=dict(use_proxy=True, proxy_fallback=True),
                  network=counts, units={}, passed=False)
    try:
        await manager.start('collector.tdx_unlocks')
        c, q = manager.registry.get('collector.tdx_unlocks'), manager.registry.get('unlocks.tdx_query')
        original = c.envelope
        def checked(unit, parents, details, cursor, observed, manifest=None):
            if unit != 'manifest':
                report['units'][unit] = dict(count=len(parents), details=len(details), digest=digest([parents, details]))
                if parents and 'representative_parent' not in report:
                    report['representative_parent'] = parents[0]
                if details and 'representative_detail' not in report:
                    report['representative_detail'] = details[0]
                if cursor['market_index'] == 0:
                    print(json.dumps(dict(unit=unit, count=len(parents), details=len(details))), flush=True)
            return original(unit, parents, details, cursor, observed, manifest)
        c.envelope = checked
        options = dict(start_month=args.start, end_month=args.end)
        cursor = await asyncio.wait_for(c.execute(fresh=True, baseline_revision=await c.checkpoint_revision(), **options), args.timeout)
        if not report['units']:
            cursor = await asyncio.wait_for(c.execute(fresh=True, baseline_revision=await c.checkpoint_revision(), **options), args.timeout)
        state = await q.state()
        for unit, expected in report['units'].items():
            if any(state['units'].get(unit, {}).get(k) != v for k, v in expected.items()):
                raise ValueError('真实规范集合与SQL证明不一致：' + unit)
        end = cursor['end']
        end_day = end[:8] + str(calendar.monthrange(int(end[:4]), int(end[5:7]))[1])
        report['audit'] = [dict(criterion=v.criterion, status=v.status, measured=v.measured, blocking=v.blocking)
            for v in await q.preparation_check(dict(start=cursor['start'], end=end_day))]
        if any(v['status'] != 'pass' for v in report['audit'] if v['criterion'] in ('keys', 'coverage', 'freshness')):
            raise ValueError('正式查询完整性核验未通过')
        store = manager.registry.get('redis.store')
        report.update(cursor=cursor, pending_stream=await store.client.xlen(store.stream),
                      errors=await manager.registry.get('collection.records').list_error_summaries(c.project_id, limit=100))
        # Public query checks the actual request-group association, not a copied list count.
        if report.get('representative_parent'):
            sample = report['representative_parent']
            report['query_sample'] = dict(list_count=len((await q.list_records(code=sample['unified_code'],
                start=sample['unlock_date'], end=sample['unlock_date']))['rows']),
                detail_count=len(await q.details(sample['group_key'])))
        settings = SettingsStore(q.mysql, store.prefix)
        if c.project_id not in await settings.load('task'):
            definition = manager.entries['collection.control'].plugin.definitions[c.project_id]
            policy = definition.default_schedule.policy(dict(enabled=definition.default_enabled, mode='manual',
                interval_seconds=definition.interval_seconds, daily_time='18:00', request_retries=2))
            await settings.save('task', c.project_id, policy)
            report['saved_default'] = policy
        report['passed'] = report['pending_stream'] == 0
        print(json.dumps({k: v for k, v in report.items() if k not in ('units', 'errors', 'representative_parent', 'representative_detail')}, ensure_ascii=False))
        return report
    finally:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', 'utf8')
        await manager.shutdown()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--start', help='YYYY-MM-01; default 1990-01-01')
    parser.add_argument('--end', help='YYYY-MM-01; default next natural year December')
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--output', default='docs/evidence/unlocks-live-2026-10-14.json')
    args = parser.parse_args()
    app = QCoreApplication([])
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
