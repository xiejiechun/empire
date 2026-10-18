"""Stopped-desktop scoped real collection through shared networking and archive."""
import argparse
import asyncio
import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.repurchases import JOB, PROJECT, extend_digest, parse
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA


async def run(args):
    cfg, lock = load_config(args.config), acquire_instance_lock()
    manager = build_manager(cfg)
    control = manager.entries['collection.control'].plugin
    control.definitions = {k: v for k, v in control.definitions.items() if k == PROJECT}
    report = dict(checked_at=datetime.now(CHINA).isoformat(), source_count=0,
                  source_digest='0'*64, requests=0, max_response_bytes=0)
    try:
        await manager.start('collector.eastmoney_repurchase')
        http = manager.registry.get('http.fetch')
        await http.configure_site('eastmoney', dict(min_interval_ms=2000, proxy_interval_ms=2000,
            total_interval_ms=2000, scaling_mode='fixed', max_concurrency=1))
        request = http.request
        async def checked_request(method, url, **kwargs):
            response = await request(method, url, **kwargs)
            after = kwargs['params'].get('filter', '').split('"')[1] if 'filter' in kwargs['params'] else ''
            rows, _ = parse(json.loads(response.content, parse_float=Decimal), after=after)
            report['source_digest'] = extend_digest(report['source_digest'], rows)
            report['source_count'] += len(rows)
            report['requests'] += 1
            report['max_response_bytes'] = max(report['max_response_bytes'], len(response.content))
            return response
        http.request = checked_request
        await manager.start('collection.control')
        saved = await control.settings.load('task')
        if PROJECT not in saved:
            await control.configure(PROJECT, control.state['jobs'][PROJECT]['policy'])
        control.state['jobs'][PROJECT]['policy'].update(use_proxy=True, proxy_fallback=True)
        active = control.tasks.get(PROJECT)
        if active is None or active.done():
            await control.run(PROJECT, origin='repurchase-live-verification', fresh=True)
        await asyncio.wait_for(control.tasks[PROJECT], args.timeout)
        job = control.state['jobs'][PROJECT]
        if job['last_status'] != 'complete':
            raise RuntimeError(job.get('error') or '回购未完成')
        query = manager.registry.get('repurchases.query')
        audit = await query.mysql.read(query.audit)
        cursor = (await manager.registry.get('ingest.publish').checkpoint(JOB))['cursor']
        if not audit['valid'] or audit['digest'] != cursor['digest']:
            raise RuntimeError('SQL规范内容集合与本轮来源证明不符')
        if report['requests'] and (report['source_count'] != audit['count'] or report['source_digest'] != audit['digest']):
            raise RuntimeError('独立来源规范摘要与SQL不符')
        checks = await query.preparation_check()
        store = manager.registry.get('redis.store')
        report.update(status=job['last_status'], audit=audit, checkpoint=cursor,
            pending_stream=await store.client.xlen(store.stream),
            saved_policy=(await control.settings.load('task'))[PROJECT],
            site=(await http.setting_store.load('site'))['eastmoney'],
            preparation=[dict(criterion=e.criterion, status=e.status, measured=e.measured) for e in checks],
            history=next((h for h in control.state['history'] if h['task_id'] == PROJECT), None))
        def inventory():
            with query.mysql.read_engine.connect() as conn:
                return dict(conn.execute(text('SELECT MIN(plan_date),MAX(plan_date),COUNT(DISTINCT unified_code) '
                    'FROM stock_repurchase_plan')).first()._mapping)
        report['inventory'] = await query.mysql.read(inventory)
        if report['pending_stream']:
            raise RuntimeError('归档队列仍有残留')
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), 'utf-8')
        print('PASS', audit['count'], 'plans;', report['requests'], 'source requests', flush=True)
    finally:
        await manager.shutdown()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--timeout', type=int, default=600)
    parser.add_argument('--report', default='docs/evidence/repurchase-live-2026-10-12.json')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
