from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from empire.contracts.plugin import Plugin, PluginContext
from empire.core.redaction import Redactor


class DependencyError(RuntimeError):
    pass


class Registry:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def get(self, capability: str) -> Any:
        if capability not in self.values:
            raise DependencyError(f"Capability is not running: {capability}")
        return self.values[capability]

    def optional(self, capability: str) -> Any | None:
        return self.values.get(capability)


@dataclass
class Entry:
    plugin: Plugin
    state: str = "STOPPED"
    error: str = ""
    context: PluginContext | None = None
    enabled: bool = False
    health: dict = field(default_factory=dict)


class PluginManager:
    def __init__(self, plugins: list[Plugin], *, redactor: Redactor | None = None) -> None:
        self.redactor = redactor or Redactor()
        self.registry = Registry()
        self.entries: dict[str, Entry] = {}
        self.providers: dict[str, str] = {}
        self.lock = asyncio.Lock()
        for plugin in plugins:
            manifest = plugin.manifest
            if manifest.id in self.entries:
                raise DependencyError(f"Duplicate plugin: {manifest.id}")
            self.entries[manifest.id] = Entry(plugin, enabled=manifest.autostart)
            for capability in manifest.provides:
                if capability in self.providers:
                    raise DependencyError(f"Ambiguous provider: {capability}")
                self.providers[capability] = manifest.id
        self.order: list[str] = []
        visiting: set[str] = set()

        def visit(plugin_id: str) -> None:
            if plugin_id in visiting:
                raise DependencyError(f"Circular dependency at {plugin_id}")
            if plugin_id in self.order:
                return
            visiting.add(plugin_id)
            for cap in self.entries[plugin_id].plugin.manifest.requires:
                if cap not in self.providers:
                    raise DependencyError(f"{plugin_id} requires missing capability {cap}")
                visit(self.providers[cap])
            visiting.remove(plugin_id)
            self.order.append(plugin_id)

        for plugin_id in self.entries:
            visit(plugin_id)

    async def autostart(self) -> None:
        for plugin_id in self.order:
            if self.entries[plugin_id].enabled:
                try:
                    await self.start(plugin_id)
                except Exception:
                    pass  # The failed entry records the reason; other plugins remain available.

    async def start(self, plugin_id: str) -> None:
        async with self.lock:
            await self._start(plugin_id)

    async def _start(self, plugin_id: str) -> None:
        entry = self.entries[plugin_id]
        if entry.context:
            entry.context.reap_finished()
        entry.enabled = True
        if entry.state == "RUNNING":
            for cap in entry.plugin.manifest.requires:
                await self._start(self.providers[cap])
            return
        if entry.context is not None:
            raise DependencyError(f"Stop incomplete or failed plugin before restart: {plugin_id}")
        entry.error = ""
        try:
            for cap in entry.plugin.manifest.requires:
                await self._start(self.providers[cap])
        except Exception as exc:
            entry.state = "BLOCKED"
            entry.error = self.redactor.text(f"Dependency unavailable: {exc}", 2048)
            raise DependencyError(entry.error) from exc
        entry.state = "STARTING"
        context = PluginContext(plugin_id, self.registry, sanitize_error=self.redactor.text,
                                on_critical_failure=lambda error: self._task_failed(entry, error))
        entry.context = context
        try:
            provided = await entry.plugin.start(context)
            context.reap_finished()
            if context.critical_failures:
                raise DependencyError("关键后台任务已退出，启动未完成")
            if set(provided) != set(entry.plugin.manifest.provides):
                raise DependencyError(f"Invalid capabilities returned by {plugin_id}")
            self.registry.values.update(provided)
            entry.state = "RUNNING"
        except BaseException as exc:
            entry.state = "FAILED"
            entry.error = entry.error or self.redactor.text(f"{type(exc).__name__}: {exc}", 2048)
            try:
                context.begin_stop()
                await entry.plugin.stop()
                await self._cancel_owned(context)
                entry.context = None
            except Exception as cleanup_error:
                entry.error = self.redactor.text(f"{entry.error}; cleanup incomplete: {cleanup_error}", 2048)
            raise

    @staticmethod
    def _task_failed(entry: Entry, error: str) -> None:
        if entry.state in ("STARTING", "RUNNING"):
            entry.state, entry.error = "FAILED", error

    async def _cancel_owned(self, context: PluginContext) -> None:
        context.begin_stop()
        tasks = list(context.tasks)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def dependents(self, plugin_id: str) -> list[str]:
        capabilities = set(self.entries[plugin_id].plugin.manifest.provides)
        return [
            key for key, entry in self.entries.items()
            if key != plugin_id and entry.context is not None
            and capabilities.intersection(entry.plugin.manifest.requires)
        ]

    async def stop(self, plugin_id: str, *, cascade: bool = False) -> None:
        async with self.lock:
            await self._stop(plugin_id, cascade=cascade)

    async def _stop(self, plugin_id: str, *, cascade: bool) -> None:
        entry = self.entries[plugin_id]
        blockers = self.dependents(plugin_id)
        if blockers and not cascade:
            raise DependencyError("Stop dependent plugins first: " + ", ".join(blockers))
        for key in reversed(self.order):
            if key in blockers:
                await self._stop(key, cascade=True)
        entry.enabled = False
        if entry.context is None:
            entry.state = "STOPPED"
            entry.error = ""
            return
        entry.state = "STOPPING"
        entry.context.begin_stop()
        try:
            await entry.plugin.stop()
            await self._cancel_owned(entry.context)
            for cap in entry.plugin.manifest.provides:
                self.registry.values.pop(cap, None)
            entry.context = None
            entry.error = ""
            entry.state = "STOPPED"
        except BaseException as exc:
            entry.error = self.redactor.text(f"stop_incomplete: {exc}", 2048)
            entry.state = "FAILED"
            raise

    async def shutdown(self) -> None:
        async with self.lock:
            errors = []
            for plugin_id in reversed(self.order):
                try:
                    await self._stop(plugin_id, cascade=False)
                except Exception as exc:
                    errors.append(f"{plugin_id}: {exc}")
            if errors:
                raise RuntimeError("; ".join(errors))

    def snapshot(self) -> dict:
        projected = {}
        for plugin_id, entry in self.entries.items():
            tasks = entry.context.task_health() if entry.context else {}
            try:
                entry.health = dict(entry.plugin.health())
            except Exception as exc:
                entry.health = {"status": "error", "error": self.redactor.text(exc, 2048)}
            if tasks:
                entry.health["background_tasks"] = tasks
            state = entry.state
            error = (entry.error or entry.health.get("error", "") or
                     "; ".join(tasks.get("recent_errors", [])))
            if state == "RUNNING" and (error or entry.health.get("status") in
                                        ("error", "degraded", "blocked", "failed")):
                state = "DEGRADED"
                error = error or "服务报告异常，请检查运行诊断"
            projected[plugin_id] = {
                "id": plugin_id, "name": entry.plugin.manifest.name,
                "description": entry.plugin.manifest.description,
                "state": state, "enabled": entry.enabled, "error": error,
                "can_start": entry.context is None and state not in ("STARTING", "STOPPING"),
                "requires": list(entry.plugin.manifest.requires),
                "health": entry.health,
            }
        for plugin_id in self.order:
            value = projected[plugin_id]
            if value["state"] != "RUNNING":
                continue
            unavailable = [projected[self.providers[cap]]["name"] for cap in value["requires"]
                           if projected[self.providers[cap]]["state"] != "RUNNING"]
            if unavailable:
                value.update(state="DEGRADED", error="依赖服务异常：" + "、".join(unavailable))
        # Defensive immutable boundary for the GUI/background thread bridge.
        return json.loads(json.dumps(self.redactor.value({"plugins": list(projected.values())}), default=str))
