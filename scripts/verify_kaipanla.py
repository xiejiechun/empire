"""Bounded real requests and formal archive/query checks; keep valid collected business data."""
import argparse
import asyncio
import copy
import json
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY
from empire.plugins.infra.settings import SettingsStore

EXAMPLES = {'000001', '600519', '920000', '001246'}
DATES = {date(2021, 1, 4), date(2021, 11, 15), date(2026, 9, 30)}


async def verify(config, output):
    cfg = copy.deepcopy(load_config(config))
    production_namespace = cfg['redis']['namespace']
    token = uuid4().hex
    cfg['redis']['namespace'] = 'empire:verify:intraday:' + token
    manager = build_manager(cfg)
    lock = acquire_instance_lock()
    mysql = store = None
    proxy = fallback = None
    result = dict(checked_at=datetime.now(CHINA).isoformat(), bounded=True,
                  development_tests_separate=True, retained_business_source='kaipanla', samples=[])
    try:
        await manager.start('collector.kaipanla_intraday')
        query = manager.entries['data.intraday'].plugin
        collector = manager.entries['collector.kaipanla_intraday'].plugin
        mysql, store = query.mysql, manager.registry.get('redis.store')
        query.namespace = production_namespace  # Read the existing stock publication proof.
        stocks, calendar = await query.plan()
        selected = [s for s in stocks if s['code'] in EXAMPLES]
        days = [d for d in calendar if d in DATES]
        if {s['code'] for s in selected} != EXAMPLES or set(days) != DATES:
            raise ValueError('指定验收证券或日期不在真实完整股票池/正式日历中')
        async def bounded_plan():
            return selected, days
        query.plan = bounded_plan
        policies = await SettingsStore(mysql, production_namespace).load('task')
        policy = policies.get('kaipanla-intraday', {})
        proxy = USE_PROXY.set(policy.get('use_proxy', True))
        fallback = PROXY_FALLBACK.set(policy.get('proxy_fallback', True))
        collector.request_retries = policy.get('request_retries', 2)
        run = await collector.execute()
        result['run'] = run
        for stock in selected:
            for day in days:
                data = await query.day(stock['market'], stock['code'], day.isoformat())
                if data is None:
                    continue
                value = data['data']
                result['samples'].append(dict(market=stock['market'], code=stock['code'],
                    day=day.isoformat(), trend_points=len(value['trend']), auction_points=len(value['auction']),
                    auction_distinct_minutes=len({p[0] for p in value['auction']}), lifecycle=value['lifecycle']))
        result['pending_validation_messages'] = await store.client.xlen(store.stream)
        result['query_source'] = query.source
        result['passed'] = run['phase'] == 'complete' and result['pending_validation_messages'] == 0
        result['limits'] = ['有限证券日实际采集，不证明全股票池全历史完整',
                            '来源量/标记原样保留；未验收分钟OHLC、成交模拟、秒级或旧版本信号']
    except Exception as exc:
        result.update(passed=False, error=redact(exc, cfg))
        if store:
            result['retained_namespace'] = store.prefix
            result['pending_validation_messages'] = await store.client.xlen(store.stream)
        raise
    finally:
        path = Path(output).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        await manager.stop('pipeline.archive', cascade=True)
        # On failure keep the validation namespace for diagnostics and replay.
        # Never discard valid pending business data or silently clear errors.
        if result.get('passed') and mysql and store:
            def cleanup_state():
                with mysql.engine.begin() as conn:
                    conn.execute(text('DELETE FROM collection_state WHERE namespace=:namespace'),
                                 {'namespace': cfg['redis']['namespace']})
            await mysql.control(cleanup_state)
            keys = [k async for k in store.client.scan_iter(match=cfg['redis']['namespace'] + ':*')]
            if keys:
                assert all(k.startswith('empire:verify:intraday:' + token + ':') for k in keys)
                await store.client.delete(*keys)
        await manager.shutdown()
        if proxy is not None:
            USE_PROXY.reset(proxy)
        if fallback is not None:
            PROXY_FALLBACK.reset(fallback)
        lock.unlock()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--config')
    parser.add_argument('--output', default='build/kaipanla-live.json')
    args = parser.parse_args()
    try:
        result = asyncio.run(verify(args.config, args.output))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(redact(exc, {}))
        raise SystemExit(1) from None
