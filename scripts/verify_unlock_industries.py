"""Collect the current industry directory through the single production path."""
import argparse
import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.unlock_industries import digest
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore


async def run(args):
    cfg, lock = load_config(args.config), acquire_instance_lock()
    manager, network = build_manager(cfg), {}
    USE_PROXY.set(True)
    PROXY_FALLBACK.set(True)
    ROUTE_COUNTS.set(network)
    report = dict(checked_at=datetime.now(UTC).isoformat(), policy=dict(use_proxy=True, proxy_fallback=True),
                  network=network, units={}, passed=False)
    try:
        await manager.start('collector.tdx_unlock_industries')
        c, q = manager.registry.get('collector.tdx_unlock_industries'), manager.registry.get('unlock_industries.tdx_query')
        original = c.envelope
        def checked(cursor, unit, rows, manifest=None):
            if unit != 'manifest':
                report['units'][unit] = dict(count=len(rows), digest=digest(rows), basis_date=cursor['basis_date'])
                if rows and 'representative' not in report:
                    report['representative'] = rows[0]
            return original(cursor, unit, rows, manifest)
        c.envelope = checked
        cursor = await asyncio.wait_for(c.execute(fresh=True, baseline_revision=await c.checkpoint_revision()), args.timeout)
        if not report['units']:
            cursor = await asyncio.wait_for(c.execute(fresh=True, baseline_revision=await c.checkpoint_revision()), args.timeout)
        from empire.contracts.preparation_scope import PreparationScope
        complete, fresh, count, missing, _, manifest = await q.mysql.read(q.audit, PreparationScope())
        if not complete or not fresh or count != cursor['collected'] or len(report['units']) != len(cursor['months']):
            raise ValueError('行业来源集合与正式SQL/范围证明不一致')
        from empire.plugins.datasets.unlock_industries import read_month
        def verify():
            with q.mysql.read_engine.connect() as conn:
                for unit, expected in report['units'].items():
                    records, rows = read_month(conn, unit)
                    if expected['count'] != len(records) or expected['digest'] != digest(rows):
                        raise ValueError('行业来源到正式查询正文集合不一致')
        await q.mysql.read(verify)
        store = manager.registry.get('redis.store')
        report.update(cursor=cursor, count=count, missing_numbers=missing, manifest=manifest,
            pending_stream=await store.client.xlen(store.stream),
            errors=await manager.registry.get('collection.records').list_error_summaries(c.project_id, limit=100),
            audit=[dict(criterion=v.criterion, status=v.status, measured=v.measured, blocking=v.blocking)
                   for v in await q.preparation_check()])
        if report.get('representative'):
            r = report['representative']
            report['query_sample'] = (await q.list_records(industry=r['industry'], start=r['unlock_month'], end=r['unlock_month']))['rows']
        settings = SettingsStore(q.mysql, store.prefix)
        if c.project_id not in await settings.load('task'):
            definition = manager.entries['collection.control'].plugin.definitions[c.project_id]
            policy = definition.default_schedule.policy(dict(enabled=definition.default_enabled, mode='manual',
                interval_seconds=definition.interval_seconds, daily_time='18:00', request_retries=2))
            await settings.save('task', c.project_id, policy)
            report['saved_default'] = policy
        report['passed'] = report['pending_stream'] == 0 and not any(v['blocking'] and v['status'] != 'pass' for v in report['audit'])
        if not report['passed']:
            raise ValueError('行业实际数据准备或归档未完成')
        print(json.dumps(dict(passed=True, months=len(cursor['months']), count=count, basis_date=cursor['basis_date'],
                             pending=report['pending_stream'], network=network)))
    finally:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', 'utf8')
        await manager.shutdown()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--output', default='docs/evidence/unlock-industries-live-2026-10-14.json')
    args = parser.parse_args()
    app = QCoreApplication([])
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
