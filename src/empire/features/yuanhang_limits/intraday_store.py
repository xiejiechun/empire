"""Volatile, bounded change snapshots. Never publishes archive envelopes."""
import json
from datetime import datetime, timedelta

from empire.core.time import CHINA
from empire.features.yuanhang_limits.contract import day_value, pool_value
from empire.features.yuanhang_limits.model import digest
from empire.features.yuanhang_limits.storage import pool_payload
from empire.features.yuanhang_limits.wire import decode, encode
from empire.plugins.infra.volatile_snapshot import SAVE

TTL = 72 * 3600
MAX_BYTES = 32 * 1024 * 1024
MAX_SNAPSHOTS = 2048



def version_at(stamp):
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError('盘中快照必须具有带时区观察时间')
    return int(stamp.timestamp() * 1000000)


class IntradayStore:
    def __init__(self, redis):
        self.redis = redis

    def keys(self, pool):
        pool_value(pool)
        prefix = f'{self.redis.prefix}:yuanhang:intraday:{pool}'
        return [prefix + ':snapshots', prefix + ':times', prefix + ':meta']

    def body_key(self, pool, version):
        pool_value(pool)
        self.parse_version(version)
        return f'{self.redis.prefix}:yuanhang:intraday:{pool}:snapshots:{version}'

    async def save(self, unit, started, finished):
        unit = pool_payload(unit)
        version = version_at(started)
        if (version_at(finished) < version or started.astimezone(CHINA).date().isoformat() != unit['trade_date']
                or finished.astimezone(CHINA).date().isoformat() != unit['trade_date']):
            raise ValueError('盘中采样时间倒序或跨日')
        body = json.dumps(dict(schema=1, started=started.isoformat(), finished=finished.isoformat(),
                               consistency='single_response' if unit['source_total'] <= 100 else 'paged_interval',
                               unit_zlib=encode(unit)), separators=(',', ':'))
        result = await self.redis.client.eval(SAVE, 3, *self.keys(unit['pool_type']),
            str(version), digest(unit), body, TTL, version_at(finished - timedelta(seconds=TTL)),
            MAX_BYTES, MAX_SNAPSHOTS, version_at(finished))
        return dict(changed=int(result[0]) == 1, stale=int(result[0]) == -1, evicted=int(result[1]))

    async def close_slot(self, pool):
        return await self.redis.client.hget(self.keys(pool)[2], 'close_slot')

    async def mark_close_slot(self, pool, slot):
        stamp = datetime.fromisoformat(slot)
        if stamp.tzinfo is None:
            raise ValueError('收盘复核窗口必须含时区')
        async with self.redis.client.pipeline(transaction=True) as p:
            p.hset(self.keys(pool)[2], 'close_slot', slot)
            p.expire(self.keys(pool)[2], TTL)
            await p.execute()

    async def timeline(self, pool, day, *, before=None, limit=200):
        day_value(day)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError('变化时刻查询上限为200')
        first = datetime.fromisoformat(day).replace(tzinfo=CHINA)
        minimum = max(version_at(first), version_at(datetime.now(CHINA) - timedelta(seconds=TTL)))
        maximum = version_at(first + timedelta(days=1)) - 1
        if before is not None:
            maximum = min(maximum, self.parse_version(before) - 1)
        values = await self.redis.client.zrevrangebyscore(self.keys(pool)[1], maximum, minimum,
                                                         start=0, num=limit + 1, withscores=True)
        return dict(versions=values[:limit], next=str(int(values[limit - 1][1])) if len(values) > limit else None)

    @staticmethod
    def parse_version(value):
        if not isinstance(value, str) or not value.isascii() or not value.isdigit() or len(value) > 16:
            raise ValueError('盘中快照版本无效')
        return int(value)

    async def read(self, pool, day, *, version=None, at=None):
        day_value(day)
        keys = self.keys(pool)
        if version is None:
            first = datetime.fromisoformat(day).replace(tzinfo=CHINA)
            end = first + timedelta(days=1)
            if at is not None:
                end = datetime.fromisoformat(day + 'T' + at).replace(tzinfo=CHINA)
            minimum = max(version_at(first), version_at(datetime.now(CHINA) - timedelta(seconds=TTL)))
            candidates = await self.redis.client.zrevrangebyscore(keys[1], version_at(end), minimum, start=0, num=1)
            if not candidates:
                return None
            version = candidates[0]
        number = self.parse_version(version)
        if number < version_at(datetime.now(CHINA) - timedelta(seconds=TTL)):
            return None
        body = await self.redis.client.get(self.body_key(pool, version))
        if body is None:
            return None  # Concurrent expiry/eviction is absence, never SQL fallback.
        if len(body) > 500 * 1024:
            raise ValueError('盘中快照正文超限')
        value = json.loads(body)
        if set(value) != {'schema', 'started', 'finished', 'consistency', 'unit_zlib'} or value['schema'] != 1:
            raise ValueError('盘中快照契约损坏')
        unit = pool_payload(decode(value['unit_zlib']), require_current=False)
        if unit['trade_date'] != day or unit['pool_type'] != pool:
            raise ValueError('盘中快照查询身份不符')
        consistency = 'single_response' if unit['source_total'] <= 100 else 'paged_interval'
        if value['consistency'] != consistency:
            raise ValueError('盘中采样一致性标记不符')
        if version_at(datetime.fromisoformat(value['started'])) != number:
            raise ValueError('盘中快照时间索引不符')
        fields = ('checked', 'evicted')
        meta = dict(zip(fields, await self.redis.client.hmget(keys[2], fields), strict=True))
        retained = await self.redis.client.zrangebyscore(keys[1],
            version_at(datetime.now(CHINA) - timedelta(seconds=TTL)), '+inf', start=0, num=1, withscores=True)
        return dict(version=version, unit=unit, started=value['started'], finished=value['finished'],
                    consistency=consistency, meta=meta, retained_since=retained[0][1] if retained else None)
