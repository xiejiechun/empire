"""Stopped-desktop, scoped invocation of the two formal tasks; no unrelated collectors start."""
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.st_events import KINDS, MARKETS, digest, project
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.collectors.tdx_st_source import parse


async def run(args):
    cfg, lock = load_config(args.config), acquire_instance_lock()
    manager = build_manager(cfg)
    control = manager.entries['collection.control'].plugin
    control.definitions = {k: v for k, v in control.definitions.items() if k in {project(x) for x in KINDS}}
    report = dict(checked_at=datetime.now(CHINA).isoformat(), tasks={})
    try:
        for kind in KINDS:
            await manager.start('collector.tdx_st_' + kind)
        http = manager.registry.get('http.fetch')
        request = http.request
        source_proofs = {}
        async def checked_request(method, url, **kwargs):
            response = await request(method, url, **kwargs)
            parameters = json.loads(kwargs['content'])['Params']
            kind = next(k for k, item in KINDS.items() if item[2] == parameters[0])
            day = parameters[2]
            groups, count = parse(kind, response.json(), day[:4]+'-'+day[4:6]+'-'+day[6:])
            source_proofs[kind] = dict(count=count, groups=groups, bytes=len(response.content))
            return response
        http.request = checked_request
        await manager.start('collection.control')
        # Scope definitions bound automatic recovery too; do not alter other saved jobs.
        for kind in KINDS:
            ident = project(kind)
            control.state['jobs'][ident]['policy'].update(use_proxy=True, proxy_fallback=True)
            active = control.tasks.get(ident)
            if active is None or active.done():
                await control.run(ident, origin='explicit-st-collection')
            await asyncio.wait_for(control.tasks[ident], args.timeout)
            job = control.state['jobs'][ident]
            if job['last_status'] != 'complete':
                raise RuntimeError(job.get('error') or ident + '未完成')
            query = manager.registry.get('st.' + kind + '.query')
            rows, state = await query.mysql.read(query.snapshot)
            checks = await query.preparation_check()
            source = source_proofs.get(kind)
            comparison = None
            if source:
                comparison = {market: source['groups'][market] == [r for r in rows if r[0].endswith('.'+market)] for market in MARKETS}
                if not all(comparison.values()):
                    raise RuntimeError('来源与SQL完整事件集合不符')
            report['tasks'][ident] = dict(source_sql_equal=comparison, source_bytes=source['bytes'] if source else None,
                sql_digest=digest(rows), date_min=min((r[1] for r in rows),default=None), date_max=max((r[1] for r in rows),default=None), status=job['last_status'], stored_events=len(rows),
                source_count=sum(r[4] for r in rows), markets=state.get('markets'),
                preparation=[dict(criterion=x.criterion, status=x.status, measured=x.measured) for x in checks],
                policy=job['policy'], history=next((h for h in control.state['history'] if h['task_id'] == ident), None))
            print(ident, job['last_status'], len(rows), flush=True)
        report['pending_stream'] = await manager.registry.get('redis.store').client.xlen(manager.registry.get('redis.store').stream)
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), 'utf-8')
    finally:
        await manager.shutdown()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--report', default='docs/evidence/st-events-live-2026-10-11.json')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
