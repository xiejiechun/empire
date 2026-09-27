"""Bounded, disposable proof of successfully archived business content."""
import hashlib
import json
import re

# One bounded bucket per dataset/source. Expiry is per entry, with whole-key expiry
# for idle sources. Both indices are changed atomically, including eviction.
CACHE_LUA = """
local clock = redis.call('TIME')
local now = tonumber(clock[1])
local expired = redis.call('ZRANGEBYSCORE', KEYS[2], '-inf', now)
for _, id in ipairs(expired) do
    redis.call('HDEL', KEYS[1], id)
    redis.call('ZREM', KEYS[2], id)
end
if ARGV[1] == 'put' then
    for i = 4, #ARGV, 2 do
        redis.call('HSET', KEYS[1], ARGV[i], ARGV[i+1])
        redis.call('ZADD', KEYS[2], now + tonumber(ARGV[2]), ARGV[i])
    end
    local excess = redis.call('ZCARD', KEYS[2]) - tonumber(ARGV[3])
    if excess > 0 then
        local oldest = redis.call('ZRANGE', KEYS[2], 0, excess - 1)
        for _, id in ipairs(oldest) do
            redis.call('HDEL', KEYS[1], id)
            redis.call('ZREM', KEYS[2], id)
        end
    end
    redis.call('EXPIRE', KEYS[1], ARGV[2])
    redis.call('EXPIRE', KEYS[2], ARGV[2])
    return {}
end
if ARGV[1] == 'forget' then
    for i = 4, #ARGV do
        redis.call('HDEL', KEYS[1], ARGV[i])
        redis.call('ZREM', KEYS[2], ARGV[i])
    end
    return {}
end
local result = {}
for i = 4, #ARGV do
    local expires = tonumber(redis.call('ZSCORE', KEYS[2], ARGV[i]) or '0')
    local valid = expires > now and expires <= now + tonumber(ARGV[2]) and expires == math.floor(expires)
    result[#result + 1] = valid and redis.call('HGET', KEYS[1], ARGV[i]) or false
end
return result
"""


def digest(content):
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


class FingerprintCache:
    def __init__(self, store, settings, version_contract):
        self.store = store
        self.version_contract = version_contract
        self.ttl = int(settings.get('fingerprint_ttl_seconds', 604800))
        self.limit = int(settings.get('fingerprint_max_entries', 10000))
        if not 1 <= self.ttl <= 31536000 or not 1 <= self.limit <= 100000:
            raise ValueError('归档摘要有效期或容量超出范围')

    def keys(self, namespace, source):
        key = f'{self.store.prefix}:archive:fingerprints:v1:{namespace}:{source}'
        return key, key + ':expiry'

    async def get(self, namespace, source, identities):
        if not identities:
            return {}
        values = await self.store.client.eval(CACHE_LUA, 2, *self.keys(namespace, source),
                                              'get', self.ttl, self.limit, *identities)
        result = {}
        for ident, raw in zip(identities, values):
            try:
                value = json.loads(raw) if raw else None
                if (isinstance(value, dict) and isinstance(value.get('hash'), str)
                        and re.fullmatch(r'[0-9a-f]{64}', value['hash'])
                        and 'version' in value):
                    self.version_contract(namespace).key(value['version'])
                    result[ident] = value
            except (ValueError, TypeError, OverflowError, RecursionError):
                pass  # Missing/corrupt proofs are cache misses, never positive evidence.
        return result

    async def put(self, namespace, source, values):
        if not values:
            return
        args, untrusted = [], []
        for ident, value in values.items():
            try:
                self.version_contract(namespace).key(value['version'])
            except (ValueError, TypeError, OverflowError):
                untrusted.append(ident)
                continue
            args.extend((ident, json.dumps(value, separators=(',', ':'))))
        if args:
            await self.store.client.eval(CACHE_LUA, 2, *self.keys(namespace, source),
                                         'put', self.ttl, self.limit, *args)
        if untrusted:
            # SQL has confirmed these records. A source clock anomaly must neither
            # block queue cleanup nor leave the previously cached version current.
            await self.store.client.eval(CACHE_LUA, 2, *self.keys(namespace, source),
                                         'forget', self.ttl, self.limit, *untrusted)

    async def invalidate(self, namespace, source):
        """Call while archiving is stopped, before manual SQL maintenance."""
        await self.store.client.delete(*self.keys(namespace, source))
