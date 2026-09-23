"""Interfaces shared by the kernel and bundled plugins."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PluginManifest:
    id: str
    name: str
    requires: tuple[str, ...] = ()
    provides: tuple[str, ...] = ()
    autostart: bool = False
    description: str = ""


class Services(Protocol):
    def get(self, capability: str) -> Any: ...


class PluginContext:
    """Only the manager creates contexts and owns their task cleanup."""

    def __init__(self, plugin_id: str, services: Services) -> None:
        self.plugin_id = plugin_id
        self.services = services
        self.logger = logging.getLogger(plugin_id)
        self.tasks: set[asyncio.Task] = set()
        self.task_errors: list[str] = []

    def get(self, capability: str) -> Any:
        return self.services.get(capability)

    def spawn(self, coroutine: Coroutine, *, name: str) -> asyncio.Task:
        task = asyncio.create_task(coroutine, name=f"{self.plugin_id}:{name}")
        self.tasks.add(task)
        task.add_done_callback(self._done)
        return task

    def _done(self, task: asyncio.Task) -> None:
        self.tasks.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            self.task_errors.append(f"{type(error).__name__}: {error}")
            self.logger.error("Owned task failed: %s", task.get_name(), exc_info=error)


class Plugin(Protocol):
    manifest: PluginManifest

    async def start(self, context: PluginContext) -> dict[str, Any]:
        """Return exactly the capability names declared by the manifest."""
        ...

    async def stop(self) -> None: ...

    def health(self) -> dict[str, Any]:
        """Cheap, nonblocking status. Never run network I/O from here."""
        ...

