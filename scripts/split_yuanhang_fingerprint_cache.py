"""Explicit stopped-client migration of financial proofs; never refresh trust or query SQL."""
import argparse
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config
from empire.features.yuanhang.dataset import FINGERPRINT_NAMESPACE, FINGERPRINT_VERSION
from empire.plugins.infra.redis_store import create_client
from empire.plugins.pipeline.fingerprints import FingerprintCache

# Exact old value and original expiry are checked at the point of copying.
# Existing destination entries always win. No runtime dual-read compatibility.
MOVE = """
local now = tonumber(redis.call('TIME')[1])
local expires = tonumber(redis.call('ZSCORE', KEYS[2], ARGV[1]) or '0')
if expires <= now or expires > now + tonumber(ARGV[3]) or expires ~= math.floor(expires)
    or redis.call('HGET', KEYS[1], ARGV[1]) ~= ARGV[2] then return 0 end
if redis.call('HEXISTS', KEYS[3], ARGV[1]) == 1 then return 0 end
if redis.call('ZCARD', KEYS[4]) >= tonumber(ARGV[4]) then return 0 end
redis.call('HSET', KEYS[3], ARGV[1], ARGV[2])
redis.call('ZADD', KEYS[4], expires, ARGV[1])
redis.call('EXPIRE', KEYS[3], ARGV[3])
redis.call('EXPIRE', KEYS[4], ARGV[3])
redis.call('HDEL', KEYS[1], ARGV[1])
redis.call('ZREM', KEYS[2], ARGV[1])
return 1
"""


async def migrate(cache, apply=False):
    source = cache.keys(FINGERPRINT_NAMESPACE, 'ths_yuanhang')
    destination = cache.keys(FINGERPRINT_NAMESPACE, 'ths_yuanhang:financial')
    client = cache.store.client
    candidates = []
    async for ident, raw in client.hscan_iter(source[0], match='*:financial', count=100):
        if len(candidates) >= cache.limit:
            raise ValueError('Existing proof bucket exceeds configured bound')
        candidates.append((ident, raw))
    report = dict(candidates=len(candidates), valid=0, moved=0, skipped=0)
    for ident, raw in candidates:
        trusted = await cache.peek(FINGERPRINT_NAMESPACE, 'ths_yuanhang', [ident])
        if ident not in trusted or cache._decode(FINGERPRINT_NAMESPACE, [ident], [raw]) != trusted:
            report['skipped'] += 1
            continue
        report['valid'] += 1
        if apply:
            report['moved'] += await client.eval(MOVE, 4, *source, *destination,
                                                ident, raw, cache.ttl, cache.limit)
    return report


async def run(config, apply):
    cfg = load_config(config)
    lock = acquire_instance_lock()
    client = create_client(cfg['redis'])
    try:
        cache = FingerprintCache(SimpleNamespace(client=client, prefix=cfg['redis']['namespace']),
                                 cfg.get('archive', {}), lambda _: FINGERPRINT_VERSION)
        return await migrate(cache, apply)
    finally:
        await client.aclose()
        lock.unlock()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(asyncio.run(run(args.config, args.apply))))
