"""Ownership and observable state for read-only UI queries."""

from __future__ import annotations

from concurrent.futures import Future
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from empire.core.time import CHINA


@dataclass
class ReadState:
    phase: str = "idle"
    started_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None


class QueryScope:
    """Own page reads; mutations intentionally remain outside this scope."""

    def __init__(self, owner):
        self.pending = set()
        self.keyed = {}
        self.states = {}
        self.closed = False
        owner.destroyed.connect(self.close)

    def track(self, future):
        self.pending = {item for item in self.pending if not item.done()}
        self.pending.add(future)
        return future

    def invoke(self, key: str, runtime, capability: str, method: str, *args):
        """Submit a read and turn synchronous submission failures into normal results."""
        self.cancel(key)
        state = self.states.setdefault(key, ReadState())
        state.phase = "loading"
        state.started_at = datetime.now(CHINA)
        try:
            if self.closed:
                raise RuntimeError("页面已经关闭")
            future = runtime.invoke(capability, method, *args)
        except Exception as exc:
            future = Future()
            future.set_exception(exc)
        self.keyed[key] = future
        return self.track(future)

    def result(self, key: str, future) -> Any:
        """Resolve the current keyed read and record success/failure freshness."""
        state = self.states.setdefault(key, ReadState())
        try:
            value = future.result()
        except Exception:
            state.phase = "error"
            state.last_error_at = datetime.now(CHINA)
            raise
        else:
            state.phase = "success"
            state.last_success_at = datetime.now(CHINA)
            return value
        finally:
            self.pending.discard(future)
            if self.keyed.get(key) is future:
                self.keyed.pop(key, None)

    def discard(self, key: str, future) -> None:
        """Ignore a completed result whose query identity is no longer current."""
        self.pending.discard(future)
        if self.keyed.get(key) is future:
            self.keyed.pop(key, None)
            self.states.setdefault(key, ReadState()).phase = "idle"

    def cancel(self, key: str) -> None:
        future = self.keyed.pop(key, None)
        if future is not None:
            future.cancel()
            self.pending.discard(future)
        self.states.setdefault(key, ReadState()).phase = "idle"

    def cancel_all(self):
        """Cancel page-owned reads while keeping the scope reusable after activation."""
        futures = list(self.pending)
        for future in futures:
            future.cancel()
        self.pending.clear()
        self.keyed.clear()
        for state in self.states.values():
            if state.phase != "closed":
                state.phase = "idle"
        return futures

    def failure_message(self, key: str, prefix: str, error: str, *, stale: bool) -> str:
        state = self.states.setdefault(key, ReadState())
        message = f"{prefix}：{error}"
        if stale:
            if state.last_success_at:
                stamp = state.last_success_at.astimezone(CHINA).strftime("%H:%M:%S")
                message += f"；当前刷新失败，显示 {stamp} 成功读取的旧数据"
            else:
                message += "；当前刷新失败，显示现有旧数据"
        return message

    def close(self, *args):
        self.closed = True
        self.cancel_all()
        for state in self.states.values():
            state.phase = "closed"
