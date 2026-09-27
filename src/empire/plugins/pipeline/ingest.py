from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from uuid import uuid4

from empire.contracts.data import (
    BackpressureError,
    BatchReservationError,
    Envelope,
    StaleCheckpointError,
)
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


@dataclass
class BatchReservation:
    owner: "IngestPlugin"
    token: str
    job_key: str
    remaining_entries: int
    remaining_bytes: int
    bytes_per_entry: int
    released: bool = False

    async def release(self):
        await self.owner.release_reservation(self)


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
        self.capacity_lock = asyncio.Lock()
        self.reservations = {}
        self.paused = False
        self.stats = {"status": "stopped", "published": 0}

    async def start(self, context: PluginContext) -> dict:
        self.redis = context.get("redis.store")
        self.archive = context.get("archive.worker")
        self.catalog = context.get("dataset.catalog")
        capacity, _ = self._capacity_settings()
        if self.archive.queue.limit < capacity:
            raise ValueError("归档消息索引容量必须覆盖入队容量")
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

    def _capacity_settings(self):
        capacity = self.settings.get("max_queue_entries", 100000)
        page_bytes = self.settings.get("max_page_bytes", 524288)
        if type(capacity) is not int or not 1 <= capacity <= 1000000:
            raise ValueError("ingest.max_queue_entries 须为 1～1000000 的整数")
        if type(page_bytes) is not int or not 1024 <= page_bytes <= 16 * 1024 * 1024:
            raise ValueError("ingest.max_page_bytes 须为 1 KiB～16 MiB 的整数")
        return capacity, page_bytes

    async def _usage(self):
        memory = await self.redis.client.info("memory")
        maximum = int(memory.get("maxmemory", 0))
        used = int(memory["used_memory"])
        queued = await self.redis.client.xlen(self.redis.stream)
        return used, maximum, queued

    async def reserve_batch(self, job_key: str, entries: int) -> BatchReservation:
        if not self.redis:
            raise RuntimeError("Ingest plugin is not running")
        self._checkpoint_key(job_key)
        if type(entries) is not int or not 1 <= entries <= 100000:
            raise ValueError("整批预留消息数须为 1～100000 的整数")
        capacity, page_bytes = self._capacity_settings()
        requested_bytes = entries * page_bytes
        async with self.capacity_lock:
            if any(item.job_key == job_key for item in self.reservations.values()):
                raise BackpressureError("该任务已有整批入队预留，请等待本轮释放后重试")
            used, maximum, queued = await self._usage()
            reserved_entries = sum(item.remaining_entries for item in self.reservations.values())
            reserved_bytes = sum(item.remaining_bytes for item in self.reservations.values())
            high = self.settings.get("high_watermark", .7)
            if queued + reserved_entries + entries > capacity:
                reason = (f"整批需要预留 {entries} 个消息槽，当前队列 {queued}、其他预留 "
                          f"{reserved_entries}、上限 {capacity}")
            elif maximum and used + reserved_bytes + requested_bytes >= maximum * high:
                reason = (f"整批最坏需要预留 {requested_bytes} 字节，Redis 当前使用 {used}、"
                          f"其他预留 {reserved_bytes}，超过 {high:.0%} 水位")
            else:
                token = uuid4().hex
                reservation = BatchReservation(
                    self, token, job_key, entries, requested_bytes, page_bytes)
                self.reservations[token] = reservation
                self.stats.update(reserved_entries=reserved_entries + entries,
                                  reserved_bytes=reserved_bytes + requested_bytes)
                return reservation
            self.paused = True
            self.stats.update(status="paused", reason=reason, queued=queued,
                              reserved_entries=reserved_entries, reserved_bytes=reserved_bytes)
            raise BackpressureError(reason)

    async def release_reservation(self, reservation: BatchReservation):
        async with self.capacity_lock:
            current = self.reservations.get(reservation.token)
            if current is reservation:
                self.reservations.pop(reservation.token)
            reservation.released = True
            reservation.remaining_entries = reservation.remaining_bytes = 0
            self.stats.update(
                reserved_entries=sum(item.remaining_entries for item in self.reservations.values()),
                reserved_bytes=sum(item.remaining_bytes for item in self.reservations.values()))

    def _check_archive_admission(self, projects=()):
        if getattr(self.archive, "blocked", False):
            raise BackpressureError("归档 schema 不兼容，采集已暂停；已有数据保留")
        if any(project in getattr(self.archive, "blocked_projects", set()) for project in projects):
            raise BackpressureError("本项目归档 schema 不兼容，采集已暂停；已有数据保留")

    async def _ensure_capacity_locked(
        self, incoming: int, reservation: BatchReservation | None,
    ) -> None:
        if not self.redis:
            raise RuntimeError("Ingest plugin is not running")
        self._check_archive_admission()
        if type(incoming) is not int or incoming < 1:
            raise ValueError("待入队消息数须为正整数")
        capacity, _ = self._capacity_settings()
        if reservation is not None:
            if (reservation.released or self.reservations.get(reservation.token) is not reservation
                    or reservation.job_key == "" or reservation.remaining_entries < incoming):
                raise BatchReservationError("整批入队预留已失效，请重新开始本轮采集")
            return
        used, maximum, queued = await self._usage()
        ratio = used / maximum if maximum else 0
        reserved = sum(item.remaining_entries for item in self.reservations.values())
        threshold = self.settings.get("low_watermark", .5) if self.paused else self.settings.get("high_watermark", .7)
        if ratio >= threshold or queued + reserved + incoming > capacity:
            self.paused = True
            self.stats.update(status="paused", memory_ratio=round(ratio, 4), queued=queued,
                              reason="Redis 内存或本项目队列达到容量水位")
            raise BackpressureError(self.stats["reason"])
        self.paused = False
        self.stats.update(status="ok", reason="", memory_ratio=round(ratio, 4))

    async def ensure_capacity(self, incoming: int = 1,
                              reservation: BatchReservation | None = None) -> None:
        async with self.capacity_lock:
            await self._ensure_capacity_locked(incoming, reservation)

    async def publish_page(
        self, envelopes: list[Envelope], *, job_key: str, expected_revision: int, cursor: dict,
        reservation: BatchReservation | None = None,
    ) -> dict:
        if not self.redis:
            raise RuntimeError("Ingest plugin is not running")
        self._check_archive_admission()
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
        values, projects = [], set()
        for event in envelopes:
            event = Envelope.model_validate(event)
            if event.job_key != job_key:
                raise ValueError("Envelope and checkpoint job keys differ")
            event = self.catalog.canonicalize(event)
            projects.add(self.catalog.project_id(event))
            values.append(event.model_dump_json())
        self._check_archive_admission(projects)
        encoded_bytes = sum(len(v.encode()) for v in values)
        if encoded_bytes > self.settings.get("max_page_bytes", 524288):
            raise ValueError("Page exceeds configured byte limit")
        capacity, _ = self._capacity_settings()
        async with self.capacity_lock:
            if reservation is not None:
                current = self.reservations.get(reservation.token)
                if (current is not reservation or reservation.released
                        or reservation.job_key != job_key
                        or reservation.remaining_entries < len(values)
                        or reservation.remaining_bytes < encoded_bytes):
                    raise BatchReservationError("整批入队预留不足或已失效，请重新开始本轮采集")
            else:
                await self._ensure_capacity_locked(len(values), None)
            # Recheck after every admission await, immediately before dispatch.
            # Once dispatched, honor the atomic Redis result; isolation cannot
            # retroactively turn a committed publication into a rejected one.
            self._check_archive_admission(projects)
            result = await self.redis.client.eval(
                PUBLISH_LUA, 2, self.redis.stream, checkpoint_key,
                expected_revision, cursor_json, len(values), capacity, *values,
            )
            if int(result[0]) == 1 and reservation is not None:
                reservation.remaining_entries -= len(values)
                reservation.remaining_bytes -= reservation.bytes_per_entry * len(values)
                if reservation.remaining_entries == 0:
                    self.reservations.pop(reservation.token, None)
                    reservation.released = True
                self.stats.update(
                    reserved_entries=sum(item.remaining_entries for item in self.reservations.values()),
                    reserved_bytes=sum(item.remaining_bytes for item in self.reservations.values()))
        if int(result[0]) != 1:
            raise StaleCheckpointError(f"游标已更新，当前版本 {result[1]}；重新读取进度后再提交")
        self.stats.update(status="ok", reason="", published=self.stats["published"] + len(values))
        self.archive.request_flush()
        return {"revision": int(result[1]), "cursor": cursor}

    async def stop(self) -> None:
        for reservation in self.reservations.values():
            reservation.released = True
            reservation.remaining_entries = reservation.remaining_bytes = 0
        self.reservations.clear()
        self.redis = self.archive = self.catalog = None
        self.stats["status"] = "stopped"

    def health(self) -> dict:
        return dict(self.stats)
