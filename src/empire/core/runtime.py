from __future__ import annotations

import asyncio
import concurrent.futures
import json
import threading
from collections.abc import Callable

from empire.core.config import redact, user_data_dir
from empire.core.manager import PluginManager


class Runtime:
    def __init__(self, factory: Callable[[], PluginManager], cfg: dict) -> None:
        self.factory = factory
        self.cfg = cfg
        self.loop: asyncio.AbstractEventLoop | None = None
        self.manager: PluginManager | None = None
        self.ready = threading.Event()
        self.closed = threading.Event()
        self.guard = threading.Lock()
        self.latest: dict = {"plugins": [], "status": "正在启动后台"}
        self.pages: tuple = ()
        self.state_file = user_data_dir() / "plugin-state.json"
        self.thread = threading.Thread(target=self._run, name="empire-runtime", daemon=False)

    def start(self) -> None:
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError("Background runtime did not initialize")

    def _run(self) -> None:
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        try:
            self.manager = self.factory()
            if self.state_file.is_file():
                try:
                    desired = json.loads(self.state_file.read_text(encoding="utf-8"))
                    for plugin_id, enabled in desired.items():
                        if plugin_id in self.manager.entries and isinstance(enabled, bool):
                            self.manager.entries[plugin_id].enabled = enabled
                except (OSError, ValueError, AttributeError):
                    pass  # Corrupt preference files do not prevent diagnostics from starting.
            self.ready.set()
            self.loop.run_until_complete(self._serve())
        except Exception as exc:
            with self.guard:
                self.latest = {"plugins": [], "error": redact(exc, self.cfg)}
            self.ready.set()
        finally:
            self.loop.run_until_complete(self.loop.shutdown_asyncgens())
            self.loop.run_until_complete(self.loop.shutdown_default_executor())
            self.loop.close()
            self.closed.set()

    async def _serve(self) -> None:
        self.exit_event = asyncio.Event()
        self.boot_task = asyncio.create_task(self.manager.autostart())
        try:
            while not self.exit_event.is_set():
                with self.guard:
                    self.pages = self.manager.registry.values.get("ui.pages", ())
                    self.latest = json.loads(redact(json.dumps(
                        self.manager.snapshot(), ensure_ascii=False
                    ), self.cfg))
                try:
                    await asyncio.wait_for(self.exit_event.wait(), timeout=.5)
                except TimeoutError:
                    pass
        finally:
            if not self.boot_task.done():
                self.boot_task.cancel()
            await asyncio.gather(self.boot_task, return_exceptions=True)

    def snapshot(self) -> dict:
        with self.guard:
            return json.loads(json.dumps(self.latest))

    def page_contributions(self) -> tuple:
        with self.guard:
            return self.pages

    def invoke(self, capability: str, method: str, *args, **kwargs) -> concurrent.futures.Future:
        """UI contributions call declared services without embedding domain logic in the kernel."""
        if self.closed.is_set() or self.loop is None:
            raise RuntimeError("后台未运行")

        async def execute():
            service = self.manager.registry.get(capability)
            return await getattr(service, method)(*args, **kwargs)

        return asyncio.run_coroutine_threadsafe(execute(), self.loop)

    def command(self, action: str, plugin_id: str = "") -> concurrent.futures.Future:
        if self.closed.is_set() or self.loop is None:
            raise RuntimeError("后台未运行")

        async def execute() -> None:
            if action == "start":
                await self.manager.start(plugin_id)
            elif action == "stop":
                await self.manager.stop(plugin_id)
            elif action == "cascade":
                await self.manager.stop(plugin_id, cascade=True)
            elif action == "flush":
                archive = self.manager.registry.get("archive.worker")
                await archive.flush()
            elif action == "shutdown":
                if not self.boot_task.done():
                    self.boot_task.cancel()
                    await asyncio.gather(self.boot_task, return_exceptions=True)
                await self.manager.shutdown()
                self.exit_event.set()
            else:
                raise ValueError(f"Unknown command: {action}")
            if action in ("start", "stop", "cascade"):
                desired = {key: entry.enabled for key, entry in self.manager.entries.items()}
                temporary = self.state_file.with_suffix(".tmp")
                temporary.write_text(json.dumps(desired, indent=2), encoding="utf-8")
                temporary.replace(self.state_file)

        return asyncio.run_coroutine_threadsafe(execute(), self.loop)
