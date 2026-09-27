from __future__ import annotations

import asyncio

import redis.asyncio as redis
from redis.backoff import NoBackoff
from redis.retry import Retry

from empire.contracts.plugin import PluginContext, PluginManifest


def create_client(settings: dict):
    options = dict(
        decode_responses=True, socket_connect_timeout=5, socket_timeout=5,
        retry=Retry(NoBackoff(), 0),
    )
    if settings.get("url"):
        return redis.Redis.from_url(settings["url"], **options)
    return redis.Redis(
        host=settings.get("host", "127.0.0.1"), port=int(settings.get("port", 6379)),
        password=settings.get("password") or None, db=int(settings.get("db", 0)),
        **options,
    )


class RedisPlugin:
    manifest = PluginManifest(
        "infra.redis", "Redis 队列与断点", provides=("redis.store",),
        description="内存保存待归档数据和采集进度；要求 noeviction，服务重启会丢失状态",
    )

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.prefix = settings.get("namespace", "empire:dev")
        self.stream = f"{self.prefix}:ingest"
        self.client = None
        self.task = None
        self.stats = {"status": "stopped"}

    async def start(self, context: PluginContext) -> dict:
        self.client = create_client(self.settings)
        server = await self.client.info("server")
        persistence = await self.client.info("persistence")
        memory = await self.client.info("memory")
        commands = await self.client.execute_command(
            "COMMAND", "INFO", "XADD", "XRANGE", "XREVRANGE", "XINFO", "XLEN", "XDEL", "EVAL", "TIME",
        )
        if not commands or not all(commands.values()):
            raise RuntimeError("Redis 缺少 Streams / Lua 必要命令")
        if memory.get("maxmemory_policy") != "noeviction":
            raise RuntimeError("Redis 必须使用 noeviction，避免未归档数据被淘汰")
        self.stats = {"status": "ok", "version": server.get("redis_version"),
                      "namespace": self.prefix, "aof_enabled": bool(persistence.get("aof_enabled")),
                      "persistence": "memory-only" if not persistence.get("aof_enabled") else "aof"}
        await self.refresh()

        async def monitor():
            while True:
                await asyncio.sleep(5)
                try:
                    await self.refresh()
                except Exception as exc:
                    self.stats.update(status="degraded", error=str(exc))

        self.task = context.spawn(monitor(), name="health", critical=True)
        return {"redis.store": self}

    async def refresh(self) -> None:
        memory = await self.client.info("memory")
        queue = await self.client.xlen(self.stream)
        used, maximum = int(memory["used_memory"]), int(memory.get("maxmemory", 0))
        self.stats.update(status="ok", error="", queued=queue,
                          used_memory=used, maxmemory=maximum,
                          memory_ratio=round(used / maximum, 4) if maximum else None)

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        if self.client:
            await self.client.aclose()
            self.client = None
        self.stats["status"] = "stopped"

    def health(self) -> dict:
        return dict(self.stats)
