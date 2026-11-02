"""Explicit checkpoint conversion; preserve all queued batches and business data."""
import argparse
import asyncio
import copy
import json
from pathlib import Path

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.features.yuanhang.contract import PRICE_JOB
from empire.features.yuanhang_limits.contract import POOLS, job
from empire.plugins.infra.redis_store import create_client

JOBS = (PRICE_JOB, *(job(pool) for pool in (*POOLS, 'reason')))


def upgrade(cursor, job_key):
    if job_key not in JOBS:
        raise ValueError('Unsupported checkpoint owner')
    result = copy.deepcopy(cursor)
    if not cursor or cursor.get('contract') == 2:
        return result
    phase = cursor.get('phase')
    if phase not in ('fetch', 'collecting', 'awaiting_archive', 'complete'):
        raise ValueError('Unknown checkpoint phase')
    page_key = 'pages' if job_key == PRICE_JOB else 'page'
    if type(cursor.get(page_key)) is not int or cursor[page_key] < 0 or not cursor.get('batch_id'):
        raise ValueError('Missing batch identity or queued page count')
    result['contract'] = 2
    if job_key == PRICE_JOB:
        if 'plans' in cursor or 'work_codes' in cursor:
            raise ValueError('Convert legacy pool plans first')
        result['maintenance_scope'] = 'recent'
        if phase == 'collecting':
            result.update(next_index=0, next_year=1900, snapshot_hash='', force_full=False, replan_recent=True)
            result.pop('current_plan', None)
    else:
        result['scope'] = 'recent'
        if phase == 'fetch':
            result.update(plan=[], index=0, remaining=None, scan_after=None,
                          force=False, replan_recent=True)
        result.pop('close_slot', None)
    assert result[page_key] == cursor[page_key] and result['batch_id'] == cursor['batch_id']
    return result


async def migrate(cfg, args):
    client = create_client(cfg['redis'])
    prefix = cfg['redis']['namespace']
    try:
        before = {key: await client.hgetall(prefix + ':checkpoint:' + key) for key in JOBS}
        converted = {key: upgrade(json.loads(value.get('cursor', '{}')), key) for key, value in before.items()}
        if args.apply:
            with Path(args.backup).open('x', encoding='utf8') as file:
                json.dump(before, file, ensure_ascii=False, indent=2)
        reports = []
        for key, value in before.items():
            original = json.loads(value.get('cursor', '{}'))
            changed = converted[key] != original
            if changed and args.apply:
                accepted = await client.eval("""
                    if redis.call('HGET',KEYS[1],'cursor') ~= ARGV[1]
                        or redis.call('HGET',KEYS[1],'revision') ~= ARGV[2] then return 0 end
                    redis.call('HSET',KEYS[1],'cursor',ARGV[3],'revision',tonumber(ARGV[2])+1)
                    return 1
                """, 1, prefix + ':checkpoint:' + key, value['cursor'], value['revision'],
                    json.dumps(converted[key], ensure_ascii=False))
                if accepted != 1:
                    raise ValueError('Concurrent checkpoint change: ' + key)
                readback = await client.hget(prefix + ':checkpoint:' + key, 'cursor')
                if json.loads(readback) != converted[key]:
                    raise ValueError('Checkpoint readback mismatch: ' + key)
            reports.append(dict(job=key, changed=changed, applied=args.apply,
                batch_preserved=original.get('batch_id') == converted[key].get('batch_id'),
                phase=converted[key].get('phase')))
        return dict(checkpoints=reports, queue_writes=0, business_dml=0)
    finally:
        await client.aclose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--backup', required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    cfg = load_config(args.config)
    lock = acquire_instance_lock()
    try:
        print(json.dumps(asyncio.run(migrate(cfg, args))))
    except Exception as exc:
        raise SystemExit(redact(exc, cfg)) from None
    finally:
        lock.unlock()


if __name__ == '__main__':
    main()
