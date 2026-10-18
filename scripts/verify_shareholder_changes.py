"""Explicit month range through the registered collector and shared archive; stopped desktop."""
import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QCoreApplication

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.tdx_performance import digest
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.collectors.tdx_performance_source import parse
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY
from empire.plugins.infra.settings import SettingsStore


async def run(args):
    cfg, lock = load_config(args.config), acquire_instance_lock()
    manager, counts = build_manager(cfg), {}
    USE_PROXY.set(True)
    PROXY_FALLBACK.set(True)
    ROUTE_COUNTS.set(counts)
    report = dict(checked_at=datetime.now(UTC).isoformat(), policy=dict(use_proxy=True, proxy_fallback=True),
                  network=counts, source={}, passed=False)
    try:
        await manager.start('collector.tdx_shareholder_changes')
        c, q = manager.registry.get('collector.tdx_shareholder_changes'), manager.registry.get('shareholder_changes.tdx_query')
        http, request = c.http, c.http.request
        async def checked_request(method, url, **kw):
            response = await request(method, url, **kw)
            try:
                month = json.loads(kw['content'])['Params'][2]
                period = month[:4] + '-' + month[4:] + '-01'
                rows, total = parse('shareholder_changes', response.json(), period)
                report['source'][period] = dict(count=total, response_bytes=len(response.content),
                    response_sha256=hashlib.sha256(response.content).hexdigest(),
                    duplicate_facts=sum(r['occurrence']>1 for r in rows),
                    markets={m: dict(count=sum(r['unified_code'].endswith(m) for r in rows),
                        digest=digest([r for r in rows if r['unified_code'].endswith(m)])) for m in ('SH', 'SZ', 'BJ')})
                if rows and 'representative_row' not in report:
                    report['representative_row'] = rows[0]
                if len(report['source']) % 20 == 0:
                    print(json.dumps(dict(months=len(report['source']), last=period,
                        rows=sum(p['count'] for p in report['source'].values()))), flush=True)
                return response
            except Exception:
                response.close()
                raise
        http.request = checked_request
        options = dict(start_month=args.start, end_month=args.end)
        baseline = await c.checkpoint_revision()
        cursor = await asyncio.wait_for(c.execute(fresh=True, baseline_revision=baseline, **options), args.timeout)
        if not report['source']:  # First finish an already queued round, then execute requested scope.
            cursor = await asyncio.wait_for(c.execute(fresh=True, baseline_revision=await c.checkpoint_revision(), **options), args.timeout)
        report['cursor'] = cursor
        state = await q.state()
        for period, proof in report['source'].items():
            for market, expected in proof['markets'].items():
                actual = state['units'].get(period + '|' + market, {})
                if any(actual.get(k) != v for k, v in expected.items()):
                    raise ValueError('来源集合与正式归档证明不一致：' + period + '|' + market)
        report['audit'] = [dict(criterion=v.criterion, status=v.status, measured=v.measured, blocking=v.blocking)
            for v in await q.preparation_check(dict(start=args.start or '', end=args.end or ''))]
        if any(v['status'] != 'pass' for v in report['audit'] if v['criterion'] in ('keys', 'coverage', 'freshness')):
            raise ValueError('正式查询完整性核验未通过')
        report['first_nonempty_month'] = min((k for k, p in report['source'].items() if p['count']), default=None)
        report['source_rows'] = sum(p['count'] for p in report['source'].values())
        report['months'] = len(report['source'])
        store = manager.registry.get('redis.store')
        report['pending_stream'] = await store.client.xlen(store.stream)
        report['errors'] = await manager.registry.get('collection.records').list_error_summaries(c.project_id, limit=100)
        settings = SettingsStore(q.mysql, store.prefix)
        saved = await settings.load('task')
        definition = manager.entries['collection.control'].plugin.definitions[c.project_id]
        if c.project_id not in saved:
            policy = definition.default_schedule.policy(dict(enabled=definition.default_enabled, mode='manual',
                interval_seconds=definition.interval_seconds, daily_time='18:00', request_retries=2))
            await settings.save('task', c.project_id, policy)
            report['saved_default'] = policy
        report['passed'] = report['pending_stream'] == 0
        print(json.dumps({k:v for k,v in report.items() if k not in ('source', 'representative_row', 'errors')}, ensure_ascii=False), flush=True)
        return report
    finally:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + '\n', 'utf8')
        await manager.shutdown()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--start', help='YYYY-MM-01; default 1990-01-01')
    parser.add_argument('--end', help='YYYY-MM-01; default current month')
    parser.add_argument('--timeout', type=int, default=3600)
    parser.add_argument('--output', default='docs/evidence/shareholder-changes-live-2026-10-13.json')
    options = parser.parse_args()
    app = QCoreApplication([])
    try:
        asyncio.run(run(options))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(options.config))) from None
