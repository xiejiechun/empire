"""Explicit retirement of the old holder gap frontier; preserve SQL proofs and history."""
import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.fingerprints import FingerprintCache

JOB = 'ths-holders-v1'


def upgrade(cursor):
    if not isinstance(cursor, dict):
        raise ValueError('Invalid holder checkpoint')
    if not cursor or cursor.get('format') == 2:
        return cursor
    if 'format' in cursor or cursor.get('phase') not in ('fetch', 'complete', 'source_gap', 'awaiting_archive'):
        raise ValueError('Unknown holder checkpoint; migration refused')
    return {}


async def migrate(cfg, args):
    client = create_client(cfg['redis'])
    key = cfg['redis']['namespace'] + ':checkpoint:' + JOB
    stream = cfg['redis']['namespace'] + ':ingest'
    fingerprints = FingerprintCache(SimpleNamespace(prefix=cfg['redis']['namespace']), {}, None)
    cache_keys = fingerprints.keys('ths_holders', 'ths')
    try:
        if await client.xlen(stream):
            raise ValueError('Pending archive queue is not empty')
        old = await client.hgetall(key)
        cursor = json.loads(old.get('cursor', '{}'))
        new = upgrade(cursor)
        if args.apply and new != cursor:
            with Path(args.backup).open('x', encoding='utf-8') as file:
                json.dump(dict(job=JOB, state=old), file, ensure_ascii=False, indent=2)
            changed = await client.eval("""
                if redis.call('HGET',KEYS[1],'cursor') ~= ARGV[1]
                    or redis.call('HGET',KEYS[1],'revision') ~= ARGV[2]
                    or redis.call('XLEN',KEYS[2]) ~= 0 then return 0 end
                redis.call('HSET',KEYS[1],'cursor','{}','revision',tonumber(ARGV[2])+1)
                redis.call('DEL',KEYS[3],KEYS[4])
                return 1
            """, 4, key, stream, *cache_keys, old['cursor'], old['revision'])
            if changed != 1:
                raise ValueError('Checkpoint or queue changed; migration refused')
        readback = await client.hgetall(key)
        if args.apply and json.loads(readback.get('cursor', '{}')) != new:
            raise ValueError('Checkpoint readback mismatch')
        return dict(job=JOB, applied=args.apply, changed=cursor != new,
                    previous_phase=cursor.get('phase'), pending=0, business_dml=0,
                    fingerprint_invalidation=bool(args.apply and cursor != new),
                    recovery='confirmed SQL security proofs; optional matching Redis fingerprints')
    finally:
        await client.aclose()


def run(args):
    cfg = load_config(args.config)
    lock = acquire_instance_lock()
    try:
        print(json.dumps(asyncio.run(migrate(cfg, args))))
    finally:
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup', required=True)
    args = parser.parse_args()
    try:
        run(args)
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
