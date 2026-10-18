"""Scoped stopped-desktop live collection and durable three-day rule schedules."""
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.contracts.trading_rules import KINDS, digest, project
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.datasets.trading_rules import canonical_payload


async def run(args):
    cfg, lock = load_config(args.config), acquire_instance_lock()
    manager = build_manager(cfg)
    control = manager.entries['collection.control'].plugin
    control.definitions = {k: v for k, v in control.definitions.items() if k in {project(x) for x in KINDS}}
    report = dict(checked_at=datetime.now(CHINA).isoformat(), source_scope='仅当前规则：沪深北普通竞价已审核条款；过户费仅2022政策公告；未补齐历史', tasks={})
    try:
        for kind in KINDS:
            await manager.start('collector.rules_' + kind)
        await manager.start('collection.control')
        for kind in KINDS:
            ident = project(kind)
            policy = {**control.state['jobs'][ident]['policy'], 'mode': 'interval', 'interval_seconds': 259200, 'enabled': True}
            await control.configure(ident, policy)
            # Development collection routes are temporary, saved user network settings persist.
            control.state['jobs'][ident]['policy'].update(use_proxy=True, proxy_fallback=True)
            active = control.tasks.get(ident)
            if active is None or active.done():
                await control.run(ident, origin='explicit-rule-collection')
            await asyncio.wait_for(control.tasks[ident], args.timeout)
            job = control.state['jobs'][ident]
            if job['last_status'] != 'complete':
                raise RuntimeError(job.get('error') or ident + '未完成')
            query = manager.registry.get('rules.' + kind + '.query')
            collector = manager.registry.get('collector.rules_' + kind)
            rows, citations, state = await query.mysql.read(query.snapshot)
            comparison = None
            if collector.last_source:
                expected = canonical_payload(kind, collector.last_source)
                comparison = rows == expected['rows'] and citations == expected['citations']
                if not comparison:
                    raise RuntimeError(ident + '来源参数/引用集合与SQL不符')
            checks = await query.preparation_check()
            report['tasks'][ident] = dict(status=job['last_status'], source_sql_equal=comparison,
                stored_parameters=len(rows), cited_clauses=len(citations), digest=digest([rows, citations]),
                effective_start=min(r['effective_start'] for r in rows), state=state, policy=policy,
                preparation=[dict(criterion=e.criterion, status=e.status, measured=e.measured) for e in checks],
                history=next((h for h in control.state['history'] if h['task_id'] == ident), None))
            print(ident, job['last_status'], len(rows), flush=True)
        store = manager.registry.get('redis.store')
        report['pending_stream'] = await store.client.xlen(store.stream)
        saved = await control.settings.load('task')
        report['saved_schedules_equal'] = all(saved[project(k)]['mode'] == 'interval' and saved[project(k)]['interval_seconds'] == 259200 for k in KINDS)
        if not report['saved_schedules_equal'] or report['pending_stream']:
            raise RuntimeError('规则计划持久化或归档清队核对未通过')
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), 'utf-8')
    finally:
        await manager.shutdown()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--timeout', type=int, default=300)
    parser.add_argument('--report', default='docs/evidence/trading-rules-live-2026-10-12.json')
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
