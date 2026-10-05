"""Stopped-desktop, scoped invocation of the two formal tasks; no unrelated collectors start."""
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.name_changes import KINDS, project
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA


async def run(args):
    cfg, lock = load_config(args.config), acquire_instance_lock()
    manager = build_manager(cfg)
    control = manager.entries['collection.control'].plugin
    control.definitions = {k: v for k, v in control.definitions.items() if k in {project(x) for x in KINDS}}
    report = dict(checked_at=datetime.now(CHINA).isoformat(), tasks={})
    try:
        for kind in KINDS:
            await manager.start('collector.tdx_' + kind + '_renames')
        await manager.start('collection.control')
        # Scope definitions bound automatic recovery too; do not alter other saved jobs.
        for kind in KINDS:
            ident = project(kind)
            active = control.tasks.get(ident)
            if active is None or active.done():
                await control.run(ident, origin='explicit-name-collection')
            await asyncio.wait_for(control.tasks[ident], args.timeout)
            job = control.state['jobs'][ident]
            if job['last_status'] != 'complete':
                raise RuntimeError(job.get('error') or ident + '未完成')
            query = manager.registry.get('names.' + kind + '.query')
            rows, state = await query.mysql.read(query.snapshot)
            checks = await query.preparation_check()
            report['tasks'][ident] = dict(status=job['last_status'], stored_events=len(rows),
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
    parser.add_argument('--report', default='docs/evidence/name-changes-live-2026-10-05.json')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
