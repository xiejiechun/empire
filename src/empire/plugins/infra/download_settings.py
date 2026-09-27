"""Durable settings, separate from in-flight HTTP resource ownership."""
import asyncio

from empire.contracts.download_settings import DEFAULTS, validate_settings
from empire.contracts.plugin import PluginManifest
from empire.plugins.infra.settings import SettingsStore


class DownloadSettingsPlugin:
    manifest = PluginManifest("infra.download_settings", "下载资源配置",
        requires=("mysql.store", "redis.store"), provides=("download.settings",),
        description="下载大小与资源额度保存到 MySQL；下次启动 HTTP 服务时生效")

    def __init__(self):
        self.store = None
        self.saved = dict(DEFAULTS)
        self.active = None
        self.lock = asyncio.Lock()

    async def start(self, context):
        self.store = SettingsStore(context.get("mysql.store"), context.get("redis.store").prefix)
        values = await self.store.load("download")
        self.saved = validate_settings(values.get("global", DEFAULTS))
        return {"download.settings": self}

    async def snapshot(self):
        return {"saved": dict(self.saved), "active": dict(self.active) if self.active is not None else None,
                "pending_restart": self.active is not None and self.saved != self.active}

    async def save(self, values):
        values = validate_settings(values)
        async with self.lock:
            if self.store is None:
                raise RuntimeError("下载配置服务未运行")
            await self.store.save("download", "global", values)
            self.saved = values  # Publish only after SQL commit; never resize in-flight owners.
            return await self.snapshot()

    def activate(self, values):
        self.active = dict(values)

    def deactivate(self):
        self.active = None

    async def stop(self):
        self.deactivate()
        self.store = None

    def health(self):
        return {"status": "ok" if self.store else "stopped",
                "pending_restart": self.active is not None and self.saved != self.active}
