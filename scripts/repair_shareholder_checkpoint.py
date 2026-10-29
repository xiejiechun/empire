"""Explicitly add a month-start proof to a legacy partial shareholder checkpoint."""
import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.features.performance.contract import digest, monthly_plan
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client


def month_base(cursor, proofs):
    periods = monthly_plan(cursor['latest'])
    units = [p + '|' + m for p in periods for m in ('SH', 'SZ', 'BJ')]
    if cursor['scope_hash'] != digest(units) or cursor['phase'] != 'fetch':
        raise ValueError('Legacy checkpoint scope mismatch')
    index, market = cursor['index'], cursor['market_index']
    if not 0 <= index < len(periods) or market not in (1, 2):
        raise ValueError('Not a partial month checkpoint')
    rolling, count, base = '', 0, None
    for i, unit in enumerate(units[:index * 3 + market]):
        if i == index * 3:
            base = dict(collected=count, rolling=rolling)
        p = proofs.get(unit, {})
        if p.get('contract') != 1 or type(p.get('count')) is not int or p['count'] < 0:
            raise ValueError('Missing archived unit proof: ' + unit)
        if not isinstance(p.get('digest'), str) or len(p['digest']) != 64:
            raise ValueError('Invalid archived unit digest: ' + unit)
        rolling = digest([rolling, unit, p['digest'], p['count']])
        count += p['count']
    if (count, rolling) != (cursor['collected'], cursor['rolling']):
        raise ValueError('Archived proof chain differs from checkpoint; no changes made')
    return base


async def run(config, apply=False):
    cfg = load_config(config)
    lock = acquire_instance_lock()
    client, engine = create_client(cfg['redis']), make_engine(cfg['mysql'])
    ns = cfg['redis']['namespace']
    key = ns + ':checkpoint:tdx-shareholder-changes-v1'
    try:
        if await client.xlen(ns + ':ingest'):
            raise ValueError('Pending archive messages must finish before proof repair')
        state = await client.hgetall(key)
        cursor = json.loads(state['cursor'])
        with engine.connect() as conn:
            payload = conn.execute(text('SELECT payload FROM collection_state WHERE namespace=:ns '
                "AND project_id='tdx-shareholder-changes'"), dict(ns=ns)).scalar_one()
        payload = json.loads(payload) if isinstance(payload, str) else payload
        base = month_base(cursor, payload.get('units', {}))
        updated = {**cursor, 'unit_base': base}
        if apply:
            changed = await client.eval("""
                if redis.call('HGET',KEYS[1],'revision') ~= ARGV[1]
                  or redis.call('HGET',KEYS[1],'cursor') ~= ARGV[2] then return 0 end
                redis.call('HSET',KEYS[1],'revision',tonumber(ARGV[1])+1,'cursor',ARGV[3])
                return 1
                """, 1, key, state['revision'], state['cursor'], json.dumps(updated))
            if not changed:
                raise ValueError('Checkpoint changed concurrently; no changes made')
        return dict(applied=apply, before=state, after_cursor=updated)
    finally:
        await client.aclose()
        engine.dispose()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.config, args.apply)), ensure_ascii=False))
