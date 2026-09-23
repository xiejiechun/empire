from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any

from empire.contracts.plugin import Plugin, PluginContext


class DependencyError(RuntimeError):
    pass


class Registry:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}

    def get(self, capability: str) -> Any:
        if capability not in self.values:
            raise DependencyError(f"Capability is not running: {capability}")
        return self.values[capability]


@dataclass
class Entry:
    plugin: Plugin
    state: str = "STOPPED"
    error: str = ""
    context: PluginContext | None = None
    enabled: bool = False
    health: dict = field(default_factory=dict)


class PluginManager:
    def __init__(self, plugins: list[Plugin]) -> None:
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
        entry.enabled = True
        if entry.state == "RUNNING":
            return
        if entry.context is not None:
            raise DependencyError(f"Stop incomplete or failed plugin before restart: {plugin_id}")
        entry.error = ""
        try:
            for cap in entry.plugin.manifest.requires:
                await self._start(self.providers[cap])
        except Exception as exc:
            entry.state = "BLOCKED"
            entry.error = f"Dependency unavailable: {exc}"
            raise DependencyError(entry.error) from exc
        entry.state = "STARTING"
        context = PluginContext(plugin_id, self.registry)
        entry.context = context
        try:
            provided = await entry.plugin.start(context)
            if set(provided) != set(entry.plugin.manifest.provides):
                raise DependencyError(f"Invalid capabilities returned by {plugin_id}")
            self.registry.values.update(provided)
            entry.state = "RUNNING"
        except BaseException as exc:
            entry.state = "FAILED"
            entry.error = f"{type(exc).__name__}: {exc}"
            try:
                await entry.plugin.stop()
                await self._cancel_owned(context)
                entry.context = None
            except Exception as cleanup_error:
                entry.error += f"; cleanup incomplete: {cleanup_error}"
            raise

    async def _cancel_owned(self, context: PluginContext) -> None:
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
        try:
            await entry.plugin.stop()
            await self._cancel_owned(entry.context)
            for cap in entry.plugin.manifest.provides:
                self.registry.values.pop(cap, None)
            entry.context = None
            entry.error = ""
            entry.state = "STOPPED"
        except BaseException as exc:
            entry.error = f"stop_incomplete: {exc}"
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
        result = []
        for plugin_id, entry in self.entries.items():
            try:
                entry.health = entry.plugin.health()
            except Exception as exc:
                entry.health = {"status": "error", "error": str(exc)}
            task_errors = entry.context.task_errors if entry.context else []
            result.append({
                "id": plugin_id, "name": entry.plugin.manifest.name,
                "description": entry.plugin.manifest.description,
                "state": entry.state, "enabled": entry.enabled,
                "error": entry.error or "; ".join(task_errors[-3:]),
                "requires": list(entry.plugin.manifest.requires),
                "health": entry.health,
            })
        # Defensive immutable boundary for the GUI/background thread bridge.
        return json.loads(json.dumps({"plugins": result}, default=str))
