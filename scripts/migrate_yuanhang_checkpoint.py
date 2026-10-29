"""Explicit conversion of old pool-plan checkpoints; no business/queue writes."""
import argparse
import asyncio
import copy
import json
from pathlib import Path

from sqlalchemy import text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.yuanhang.contract import FINANCIAL_JOB, PRICE_JOB
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.sources.yuanhang_payload import digest


def upgrade(cursor, codes):
    result = copy.deepcopy(cursor)
    if not {'plans', 'work_codes'} & cursor.keys():
        return result
    if cursor.get('scope_hash') != digest(codes):
        raise ValueError('Checkpoint stock scope differs; conversion refused')
    work, plans, index = cursor['work_codes'], cursor['plans'], cursor['next_index']
    if (work != sorted(set(work)) or set(work) - set(codes) or set(plans) != set(work)
            or type(index) is not int or not 0 <= index <= len(work)):
        raise ValueError('Invalid old work plan; conversion refused')
    position = len(codes) if index == len(work) else codes.index(work[index])
    if cursor['phase'] in ('complete', 'awaiting_archive') and index != len(work):
        raise ValueError('Incomplete old work cannot be marked complete')
    if cursor.get('snapshot_hash') or cursor.get('next_year', 1900) != 1900:
        if index == len(work):
            raise ValueError('Partial security outside old work plan')
        result['current_plan'] = plans[work[index]]
    result.update(next_index=position, skipped_units=position-index,
                  force_full=bool(plans) and all(p.get('reason') == 'explicit_full_verification'
                                                for p in plans.values()))
    del result['plans'], result['work_codes']
    if len(json.dumps(result, ensure_ascii=False).encode()) > 16384:
        raise ValueError('Converted checkpoint still exceeds shared bound')
    return result


async def migrate(cfg, args, codes):
    client = create_client(cfg['redis'])
    key = cfg['redis']['namespace'] + ':checkpoint:' + args.job
    try:
        if await client.xlen(cfg['redis']['namespace'] + ':ingest'):
            raise ValueError('Pending archive queue is not empty')
        old = await client.hgetall(key)
        cursor = json.loads(old.get('cursor', '{}'))
        new = upgrade(cursor, codes)
        if args.apply and new != cursor:
            with Path(args.backup).open('x', encoding='utf-8') as file:
                json.dump(dict(job=args.job, state=old), file, ensure_ascii=False, indent=2)
            changed = await client.eval("""
                if redis.call('HGET',KEYS[1],'cursor') ~= ARGV[1]
                    or redis.call('HGET',KEYS[1],'revision') ~= ARGV[2]
                    or redis.call('XLEN',KEYS[2]) ~= 0 then return 0 end
                redis.call('HSET',KEYS[1],'cursor',ARGV[3],'revision',tonumber(ARGV[2])+1)
                return 1
            """, 2, key, cfg['redis']['namespace'] + ':ingest', old['cursor'], old['revision'],
                json.dumps(new, ensure_ascii=False))
            if changed != 1:
                raise ValueError('Checkpoint or queue changed; conversion refused')
        readback = await client.hgetall(key)
        if args.apply and json.loads(readback.get('cursor', '{}')) != new:
            raise ValueError('Converted checkpoint readback mismatch')
        return dict(job=args.job, applied=args.apply, changed=cursor != new,
                    before_bytes=len(old.get('cursor', '').encode()),
                    after_bytes=len(json.dumps(new, ensure_ascii=False).encode()),
                    before_index=cursor.get('next_index'), after_index=new.get('next_index'),
                    batch_preserved=cursor.get('batch_id') == new.get('batch_id'), pending=0, business_dml=0)
    finally:
        await client.aclose()


def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock()
    engine = make_engine(cfg['mysql'])
    try:
        with engine.connect() as conn:
            codes = list(conn.execute(text('SELECT unified_code FROM stock ORDER BY unified_code LIMIT 15001')).scalars())
            if not 1 <= len(codes) <= 15000:
                raise ValueError('Stock pool empty or exceeds bound')
        print(json.dumps(asyncio.run(migrate(cfg, args, codes))))
    finally:
        engine.dispose()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--job', choices=(PRICE_JOB, FINANCIAL_JOB), default=PRICE_JOB)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
