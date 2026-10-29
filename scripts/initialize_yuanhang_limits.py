"""Explicit historical initialization through the formal collectors; Empire must be closed."""
import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.yuanhang_limits.contract import POOLS, job
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


async def require_owned_pending(store):
    marker = '-'
    allowed = {job(kind) for kind in [*POOLS, 'reason']}
    while True:
        messages = await store.client.xrange(store.stream, min=marker, count=256)
        if not messages:
            return
        for _, fields in messages:
            raw = fields.get('envelope')
            if not raw or json.loads(raw).get('job_key') not in allowed:
                raise RuntimeError('队列含非本次涨跌停任务消息，拒绝启动初始化归档器')
        marker = '(' + messages[-1][0]


async def run(args):
    cfg = load_config(args.config)
    report_path = Path(args.report)
    if report_path.exists():
        raise FileExistsError('初始化报告须使用新路径，不覆盖已有证据')
    lock = acquire_instance_lock() if args.apply else None
    manager = build_manager(cfg)
    routes = {}
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(routes)
    report = dict(started_at=datetime.now(UTC).isoformat(), applied=args.apply, complete=False,
                  network_policy=dict(use_proxy=True, proxy_fallback=True), projects={}, errors=[])
    root = Path(__file__).resolve().parents[1]
    paths = [*root.glob('src/empire/features/yuanhang_limits/*.py'), Path(__file__).resolve(), root / 'sql/schema.sql', root / 'src/empire/sources/security_identity.py']

    def bindings():
        return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}

    report['bindings'] = bindings()

    def save():
        report['routes'] = dict(routes)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), 'utf8')

    try:
        await manager.start('data.yuanhang_limits')
        query = manager.registry.get('yuanhang.limits.query')
        report['target'] = await query.read(lambda conn: dict(conn.execute(text(
            'SELECT DATABASE() AS database_name,@@server_uuid AS server_uuid')).mappings().one()))
        report['target']['namespace'] = cfg['redis'].get('namespace', 'empire')
        report['first'] = '1990-12-19'
        preview = await query.collection_plan('limit_up_pool', through=args.through)
        report['through'] = preview['cutoff']
        report['initial_pool_plan'] = preview
        if not args.apply:
            return
        original_plan = query.collection_plan

        async def fixed_plan(pool, **kwargs):
            kwargs['through'] = report['through']
            return await original_plan(pool, **kwargs)

        query.collection_plan = fixed_plan
        await manager.start('infra.redis')
        store = manager.registry.get('redis.store')
        await require_owned_pending(store)
        for kind in [*POOLS, *([] if args.pools_only else ['reason'])]:
            if kind == 'reason' and report['errors']:
                report['reason_deferred'] = '五池尚有失败，保留原因任务待五池完整后继续'
                break
            ident = 'collector.yuanhang_limits_' + kind
            await manager.start(ident)
            collector = manager.registry.get(ident)
            collector.request_retries = 2

            async def progress():
                while True:
                    await asyncio.sleep(30)
                    state = dict(project=collector.project_id, **collector.health())
                    print(json.dumps(state, ensure_ascii=False, default=str), flush=True)
                    report['projects'][kind] = state
                    save()

            monitor = asyncio.create_task(progress())
            try:
                result = await collector.execute(baseline_revision=await collector.checkpoint_revision(), history_only=True)
                if result['cutoff'] != report['through']:
                    raise RuntimeError('恢复断点截止日与本轮范围不一致，请显式使用原截止日完成后再维护新增日期')
                report['projects'][kind] = dict(cursor=result, stats=collector.health())
                scope = dict(start=report['first'], end=result['cutoff'])
                checks = await getattr(query, 'check_' + kind)(scope)
                report['projects'][kind]['audit'] = [dict(criterion=e.criterion, status=e.status, measured=e.measured)
                                                    for e in checks]
                if kind != 'reason':
                    report['projects'][kind]['coverage'] = await query.read(lambda conn: dict(conn.execute(text(
                        'SELECT COUNT(*) AS dates,SUM(source_total) AS members,SUM(source_total=0) AS source_empty_dates,'
                        'MIN(trade_date) AS first_checked,MAX(trade_date) AS last_checked,'
                        'MIN(CASE WHEN source_total>0 THEN trade_date END) AS first_nonempty '
                        'FROM yuanhang_limit_pool WHERE pool_type=:pool AND trade_date<=:through'),
                        dict(pool=kind, through=result['cutoff'])).mappings().one()))
                if any(e.status != 'pass' for e in checks if e.criterion != 'temporal'):
                    report['errors'].append(dict(project=collector.project_id, error='历史范围数据准备未通过'))
            except Exception as exc:
                report['errors'].append(dict(project=collector.project_id, error=redact(exc, cfg)))
            finally:
                monitor.cancel()
                await asyncio.gather(monitor, return_exceptions=True)
                save()
        report['pending'] = await store.client.xlen(store.stream)
        report['pools_complete'] = not report['errors'] and report['pending'] == 0 and all(k in report['projects'] for k in POOLS)
        report['complete'] = not report['errors'] and report['pending'] == 0 and len(report['projects']) == 6
        if args.pools_only:
            report['reason_deferred'] = '本轮显式只完成五池；原因须由后续完整初始化继续，不能宣称全数据完成'
    finally:
        await manager.shutdown()
        if bindings() != report['bindings']:
            report['complete'] = False
            report['errors'].append(dict(error='运行期间来源实现或结构改变，当前报告不能作为最终验收'))
        report['finished_at'] = datetime.now(UTC).isoformat()
        save()
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])
        if lock:
            lock.unlock()
    if args.apply and not (report['complete'] or args.pools_only and report.get('pools_complete') and not report['errors']):
        raise RuntimeError('初始化尚有未完成范围，详见脱敏报告；保留正式断点和待归档消息')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--through', help='固定已结束交易日；跨日续跑使用原报告截止日')
    parser.add_argument('--pools-only', action='store_true', help='仅补齐并审计五池；原因明确留待后续，不标记全数据完成')
    parser.add_argument('--report', required=True)
    arguments = parser.parse_args()
    try:
        asyncio.run(run(arguments))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(arguments.config))) from None
