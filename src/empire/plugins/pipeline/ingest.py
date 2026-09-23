from __future__ import annotations

import json
import re

from empire.contracts.data import BackpressureError, Envelope, StaleCheckpointError
from empire.contracts.plugin import PluginContext, PluginManifest

PUBLISH_LUA = """
local checkpoint_type = redis.call('TYPE', KEYS[2]).ok
local stream_type = redis.call('TYPE', KEYS[1]).ok
if checkpoint_type ~= 'none' and checkpoint_type ~= 'hash' then
    return redis.error_reply('INVALID_CHECKPOINT_TYPE')
end
if stream_type ~= 'none' and stream_type ~= 'stream' then
    return redis.error_reply('INVALID_STREAM_TYPE')
end
local revision = tonumber(redis.call('HGET', KEYS[2], 'revision') or '0')
if revision ~= tonumber(ARGV[1]) then return {0, revision} end
local count = tonumber(ARGV[3])
if redis.call('XLEN', KEYS[1]) + count > tonumber(ARGV[4]) then
    return redis.error_reply('QUEUE_CAPACITY_EXCEEDED')
end
for i = 1, count do
    redis.call('XADD', KEYS[1], '*', 'envelope', ARGV[4 + i])
end
redis.call('HSET', KEYS[2], 'revision', revision + 1, 'cursor', ARGV[2])
return {1, revision + 1}
"""


class IngestPlugin:
    manifest = PluginManifest(
        "pipeline.ingest", "采集入队与进度", requires=("redis.store", "archive.worker", "dataset.catalog"),
        provides=("ingest.publish",), description="消息先入 Redis，再原子推进游标；高水位暂停",
    )

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.redis = None
        self.archive = None
        self.catalog = None
        self.paused = False
        self.stats = {"status": "stopped", "published": 0}

    async def start(self, context: PluginContext) -> dict:
        self.redis = context.get("redis.store")
        self.archive = context.get("archive.worker")
        self.catalog = context.get("dataset.catalog")
        self.paused = False
        self.stats = {"status": "ok", "published": 0}
        return {"ingest.publish": self}

    def _checkpoint_key(self, job_key: str) -> str:
        if not re.fullmatch(r"[A-Za-z0-9:_-]{1,100}", job_key):
            raise ValueError("Job key must use simple ASCII identifiers")
        return f"{self.redis.prefix}:checkpoint:{job_key}"

    async def checkpoint(self, job_key: str) -> dict:
        state = await self.redis.client.hgetall(self._checkpoint_key(job_key))
        return {"revision": int(state.get("revision", 0)),
                "cursor": json.loads(state.get("cursor", "{}"))}

    async def advance_checkpoint(self, *, job_key: str, expected_revision: int, cursor: dict):
        """Finalize already durable business data without enqueueing operational records."""
        encoded = json.dumps(cursor, ensure_ascii=False, allow_nan=False)
        if len(encoded.encode()) > 16384:
            raise ValueError("Checkpoint is too large")
        result = await self.redis.client.eval("""
            local revision = tonumber(redis.call('HGET', KEYS[1], 'revision') or '0')
            if revision ~= tonumber(ARGV[1]) then return {0,revision} end
            redis.call('HSET', KEYS[1], 'revision', revision+1, 'cursor', ARGV[2])
            return {1,revision+1}
        """, 1, self._checkpoint_key(job_key), expected_revision, encoded)
        if int(result[0]) != 1:
            raise StaleCheckpointError("游标已更新，请重新读取进度")
        return {"revision": int(result[1]), "cursor": cursor}

    async def ensure_capacity(self, incoming: int = 1) -> None:
        if not self.redis:
            raise RuntimeError("Ingest plugin is not running")
        if getattr(self.archive, "blocked", False):
            raise BackpressureError("归档 schema 不兼容，采集已暂停；已有数据保留")
        memory = await self.redis.client.info("memory")
        maximum = int(memory.get("maxmemory", 0))
        ratio = int(memory["used_memory"]) / maximum if maximum else 0
        queued = await self.redis.client.xlen(self.redis.stream)
        capacity = int(self.settings.get("max_queue_entries", 100000))
        threshold = self.settings.get("low_watermark", .5) if self.paused else self.settings.get("high_watermark", .7)
        if ratio >= threshold or queued + incoming > capacity:
            self.paused = True
            self.stats.update(status="paused", memory_ratio=round(ratio, 4), queued=queued,
                              reason="Redis 内存或本项目队列达到容量水位")
            raise BackpressureError(self.stats["reason"])
        self.paused = False
        self.stats.update(status="ok", reason="", memory_ratio=round(ratio, 4))

    async def publish_page(
        self, envelopes: list[Envelope], *, job_key: str, expected_revision: int, cursor: dict,
    ) -> dict:
        if not self.redis:
            raise RuntimeError("Ingest plugin is not running")
        if getattr(self.archive, "blocked", False):
            raise BackpressureError("归档 schema 不兼容，采集已暂停；已有数据保留")
        if not envelopes or len(envelopes) > 500:
            raise ValueError("A page must contain 1 to 500 envelopes")
        if not isinstance(expected_revision, int) or expected_revision < 0:
            raise ValueError("Checkpoint revision must be nonnegative")
        if not isinstance(cursor, dict):
            raise ValueError("Cursor must be an object")
        checkpoint_key = self._checkpoint_key(job_key)
        cursor_json = json.dumps(cursor, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
        if len(cursor_json.encode()) > 16384:
            raise ValueError("Checkpoint is too large")
        values = []
        for event in envelopes:
            event = Envelope.model_validate(event)
            if event.job_key != job_key:
                raise ValueError("Envelope and checkpoint job keys differ")
            event = self.catalog.canonicalize(event)
            values.append(event.model_dump_json())
        if sum(len(v.encode()) for v in values) > self.settings.get("max_page_bytes", 524288):
            raise ValueError("Page exceeds configured byte limit")
        await self.ensure_capacity(len(values))
        capacity = int(self.settings.get("max_queue_entries", 100000))
        result = await self.redis.client.eval(
            PUBLISH_LUA, 2, self.redis.stream, checkpoint_key,
            expected_revision, cursor_json, len(values), capacity, *values,
        )
        if int(result[0]) != 1:
            raise StaleCheckpointError(f"游标已更新，当前版本 {result[1]}；重新读取进度后再提交")
        self.stats.update(status="ok", reason="", published=self.stats["published"] + len(values))
        return {"revision": int(result[1]), "cursor": cursor}

    async def stop(self) -> None:
        self.redis = self.archive = self.catalog = None
        self.stats["status"] = "stopped"

    def health(self) -> dict:
        return dict(self.stats)
