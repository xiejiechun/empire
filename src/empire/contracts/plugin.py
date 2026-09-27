"""Interfaces shared by the kernel and bundled plugins."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable, Coroutine
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
    def optional(self, capability: str) -> Any | None: ...


class PluginContext:
    """Only the manager creates contexts and owns their task cleanup."""

    def __init__(self, plugin_id: str, services: Services, *,
                 sanitize_error: Callable[[object], str],
                 on_critical_failure: Callable[[str], None] | None = None) -> None:
        self.plugin_id = plugin_id
        self.services = services
        self.logger = logging.getLogger(plugin_id)
        self.tasks: set[asyncio.Task] = set()
        self.task_errors: deque[str] = deque(maxlen=100)
        self._critical: set[asyncio.Task] = set()
        self._sanitize_error = sanitize_error
        self._on_critical_failure = on_critical_failure
        self.stopping = False
        self.error_count = 0
        self.critical_failures = 0

    def get(self, capability: str) -> Any:
        return self.services.get(capability)

    def optional(self, capability: str) -> Any | None:
        return self.services.optional(capability)

    def spawn(self, coroutine: Coroutine, *, name: str, critical: bool = False) -> asyncio.Task:
        """Critical resident tasks must not exit before the owner begins stopping."""
        if self.stopping:
            coroutine.close()
            raise RuntimeError("Plugin is stopping; cannot spawn new work")
        task = asyncio.create_task(coroutine, name=f"{self.plugin_id}:{name}")
        self.tasks.add(task)
        if critical:
            self._critical.add(task)
        task.add_done_callback(self._done)
        return task

    def begin_stop(self) -> None:
        self.reap_finished()
        self.stopping = True

    def reap_finished(self) -> None:
        # A finished task may still be waiting for its done callback's next turn.
        for task in tuple(self.tasks):
            if task.done():
                self._done(task)

    def _done(self, task: asyncio.Task) -> None:
        if task not in self.tasks:
            return
        self.tasks.remove(task)
        critical = task in self._critical
        self._critical.discard(task)
        error = None if task.cancelled() else task.exception()
        unexpected = critical and not self.stopping
        if error is None and not unexpected:
            return
        try:
            detail = (f"{type(error).__name__}: {error}" if error is not None else
                      "意外取消" if task.cancelled() else "意外退出")
            safe = self._sanitize_error(f"后台任务 {task.get_name()}：{detail}")
        except Exception:
            safe = "后台任务异常（错误详情无法安全格式化）"
        safe = safe.encode("utf-8")[:2048].decode("utf-8", errors="ignore")
        self.task_errors.append(safe)
        self.error_count += 1
        # Never retain or log the raw exception/traceback, which can contain secrets.
        self.logger.error("%s", safe)
        if unexpected:
            self.critical_failures += 1
            if self._on_critical_failure:
                self._on_critical_failure(safe)

    def task_health(self) -> dict:
        self.reap_finished()
        return {"status": "stopping" if self.stopping else
                "failed" if self.critical_failures else "ok",
                "active": len(self.tasks), "critical_active": len(self._critical),
                "critical_failures": self.critical_failures, "errors_total": self.error_count,
                "recent_errors": list(self.task_errors)[-3:]}


class Plugin(Protocol):
    manifest: PluginManifest

    async def start(self, context: PluginContext) -> dict[str, Any]:
        """Return exactly the capability names declared by the manifest."""
        ...

    async def stop(self) -> None: ...

    def health(self) -> dict[str, Any]:
        """Cheap, nonblocking status. Never run network I/O from here."""
        ...
