"""Bounded Redis-only changes, separate from daily coverage and archive queues."""
import json
from datetime import datetime, timedelta

from empire.core.time import CHINA
from empire.features.graymarket.codec import pack, unpack
from empire.features.graymarket.contract import day, digest
from empire.plugins.infra.volatile_snapshot import SAVE

TTL = 72 * 3600
MAX_BYTES = 32 * 1024 * 1024
MAX_SNAPSHOTS = 2048


def version_at(stamp):
    if not isinstance(stamp, datetime) or stamp.tzinfo is None:
        raise ValueError("盘中观察时间必须含时区")
    return int(stamp.timestamp() * 1000000)


class IntradayStore:
    def __init__(self, redis):
        self.redis = redis

    def keys(self):
        prefix = f"{self.redis.prefix}:graymarket:intraday"
        return [prefix + ":snapshots", prefix + ":times", prefix + ":meta"]

    def body_key(self, version):
        self.parse_version(version)
        return f"{self.redis.prefix}:graymarket:intraday:snapshots:{version}"

    @staticmethod
    def parse_version(value):
        if not isinstance(value, str) or not value.isascii() or not value.isdigit() or not 1 <= len(value) <= 16:
            raise ValueError("盘中快照版本无效")
        return int(value)

    async def save(self, stamp, rows, started, finished):
        day(stamp)
        version = version_at(started)
        if version_at(finished) < version or any(
            t.astimezone(CHINA).date().isoformat() != stamp for t in (started, finished)
        ):
            raise ValueError("盘中采样倒序或跨日")
        summary = digest([stamp, rows])
        async def publish(body):
            return await self.redis.client.eval(SAVE, 3, *self.keys(), str(version),
                summary, body, TTL, version_at(finished - timedelta(seconds=TTL)),
                MAX_BYTES, MAX_SNAPSHOTS, version_at(finished))
        result = await publish("")
        if int(result[0]) != -2:
            return dict(changed=int(result[0]) == 1, stale=int(result[0]) == -1, evicted=int(result[1]))
        body = json.dumps(dict(schema=1, date=stamp, rows=pack(rows),
            started=started.isoformat(), finished=finished.isoformat(),
            consistency="single_response" if len(rows) <= 100 else "paged_interval"), separators=(",", ":"))
        result = await publish(body)
        return dict(changed=int(result[0]) == 1, stale=int(result[0]) == -1, evicted=int(result[1]))

    async def maintenance(self):
        return await self.redis.client.hget(self.keys()[2], "maintenance")

    async def mark_maintenance(self, slot):
        if datetime.fromisoformat(slot).tzinfo is None:
            raise ValueError("收盘维护窗口必须含时区")
        slot = datetime.fromisoformat(slot).astimezone(CHINA).isoformat(timespec="minutes")
        await self.redis.client.eval("""
            local old = redis.call('HGET', KEYS[1], 'maintenance')
            if old and old >= ARGV[1] then return 0 end
            redis.call('HSET', KEYS[1], 'maintenance', ARGV[1])
            redis.call('EXPIRE', KEYS[1], ARGV[2])
            return 1
        """, 1, self.keys()[2], slot, TTL)

    async def read(self, stamp, *, version=None):
        day(stamp)
        first = datetime.fromisoformat(stamp).replace(tzinfo=CHINA)
        minimum = max(version_at(first), version_at(datetime.now(CHINA) - timedelta(seconds=TTL)))
        if version is None:
            candidates = await self.redis.client.zrevrangebyscore(self.keys()[1],
                version_at(first + timedelta(days=1)) - 1, minimum, start=0, num=1)
            if not candidates:
                return None
            version = candidates[0]
        number = self.parse_version(version)
        if number < minimum:
            return None
        body = await self.redis.client.get(self.body_key(version))
        if body is None:
            return None
        if len(body) > 500 * 1024:
            raise ValueError("盘中快照正文超限")
        value = json.loads(body)
        if set(value) != {"schema", "date", "rows", "started", "finished", "consistency"} or value["schema"] != 1:
            raise ValueError("盘中快照契约损坏")
        rows = unpack(value["rows"])
        started, finished = [datetime.fromisoformat(value[k]) for k in ("started", "finished")]
        if (value["date"] != stamp or version_at(started) != number or version_at(finished) < number
            or any(t.astimezone(CHINA).date().isoformat() != stamp for t in (started, finished))
            or value["consistency"] != ("single_response" if len(rows) <= 100 else "paged_interval")):
            raise ValueError("盘中快照身份或时间不符")
        return dict(value, rows=rows, version=version)
