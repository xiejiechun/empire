"""Bounded proxy-only actual source verification of seven formal products."""
import argparse
import asyncio
import json
from datetime import datetime
from pathlib import Path

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS
from empire.plugins.datasets.kaipanla_products import digest, point_count
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


async def verify(config, output):
    cfg = load_config(config)
    manager = build_manager(cfg)
    lock = acquire_instance_lock()
    counts = {'proxy_requests': 0, 'direct_requests': 0, 'fallback_requests': 0}
    tokens = (USE_PROXY.set(True), PROXY_FALLBACK.set(False), ROUTE_COUNTS.set(counts))
    report = dict(checked_at=datetime.now(CHINA).isoformat(), samples=[], bounded=True,
                  full_history_collection_started=False, automatic_policies_changed=False)
    try:
        await manager.start('data.kaipanla_trend')
        planning = manager.entries['data.kaipanla_trend'].plugin
        stocks, days = await planning.plan()
        selected = [s for s in stocks if s['code'] in {'000001', '600000'}]
        if len(selected) != 2:
            raise ValueError('指定沪深验收证券不在正式股票池')
        day = days[-1]
        async def plan():
            return selected, [day]
        for kind in PRODUCTS:
            await manager.start('collector.kaipanla_' + kind)
            collector = manager.entries['collector.kaipanla_' + kind].plugin
            query = manager.entries['data.kaipanla_' + kind].plugin
            query.plan = plan
            run = await collector.execute()
            for stock in selected:
                value = await query.day(stock['market'], stock['code'], day.isoformat())
                if value is None:
                    raise ValueError('正式查询缺少实际已归档证券日')
                report['samples'].append(dict(kind=kind, security=stock['code'] + '.' + stock['market'],
                    trade_date=day.isoformat(), points=point_count(value['data']), business_hash=digest(value['data'])))
            evidence = await query.preparation_check({'codes': ['000001', '600000'],
                'start': day.isoformat(), 'end': day.isoformat()})
            report.setdefault('preparation', {})[kind] = [dict(criterion=e.criterion, status=e.status) for e in evidence]
            if run['phase'] != 'complete' or any(e.status != 'pass' for e in evidence):
                raise ValueError('实际归档或声明范围数据准备未通过')
        store = manager.registry.get('redis.store')
        report['pending_messages'] = await store.client.xlen(store.stream)
        report['passed'] = report['pending_messages'] == 0 and len(report['samples']) == 14 and counts['direct_requests'] == 0
    except Exception as exc:
        report.update(passed=False, error=redact(exc, cfg))
    finally:
        report['route_counts'] = counts
        await manager.shutdown()
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        ROUTE_COUNTS.reset(tokens[2])
        lock.unlock()
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report.get('passed') else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--output', default='build/kaipanla-seven-live.json')
    args = parser.parse_args()
    raise SystemExit(asyncio.run(verify(args.config, args.output)))
