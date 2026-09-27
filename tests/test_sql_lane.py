import asyncio
import threading
from unittest.mock import MagicMock

import pytest

from empire.plugins.infra.mysql_store import MySQLPlugin
from empire.plugins.infra.sql_lane import SQLLane


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


async def test_bounded_admission_and_queued_cancellation():
    lane = SQLLane("test-sql-bounded", 1, 1)
    release, entered = threading.Event(), threading.Event()
    ran = []

    def slow():
        entered.set()
        assert release.wait(3)

    first = asyncio.create_task(lane.call(slow))
    queued = None
    try:
        await until(entered.is_set)
        queued = asyncio.create_task(lane.call(lambda: ran.append(True)))
        await until(lambda: lane.pending == 2)
        with pytest.raises(RuntimeError, match="队列已满"):
            await lane.call(lambda: None)
        assert lane.health() == {"active": 1, "waiting": 1, "workers": 1,
                                 "capacity": 2, "rejected": 1}
        queued.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued
        assert lane.pending == 1 and not ran
    finally:
        release.set()
        await asyncio.gather(first, *([queued] if queued else []), return_exceptions=True)
        await lane.close()
    assert lane.pending == lane.active == 0


@pytest.mark.parametrize("fails", [False, True])
async def test_repeated_cancellation_retains_worker_ownership(fails):
    lane = SQLLane("test-sql-cancel", 1, 1)
    entered, release, completed = threading.Event(), threading.Event(), threading.Event()

    def operation():
        entered.set()
        assert release.wait(3)
        completed.set()
        if fails:
            raise ValueError("test failure after cancellation")

    task = asyncio.create_task(lane.call(operation))
    try:
        await until(entered.is_set)
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and lane.active == 1
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert completed.is_set() and lane.pending == 0
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await lane.close()


async def test_worker_exception_releases_capacity():
    lane = SQLLane("test-sql-error", 1, 0)
    try:
        with pytest.raises(ZeroDivisionError):
            await lane.call(lambda: 1 / 0)
        assert await lane.call(lambda: 42) == 42
    finally:
        await lane.close()


async def test_plugin_isolates_pools_drains_shutdown_and_restarts(monkeypatch):
    engines = []

    def factory(settings, *, pool_size):
        engine = MagicMock()
        engine.size = pool_size
        engines.append(engine)
        return engine

    monkeypatch.setattr("empire.plugins.infra.mysql_store.make_engine", factory)
    monkeypatch.setattr(MySQLPlugin, "_validate", lambda self: "test")
    plugin = MySQLPlugin({"database": "test"})
    await plugin.start(None)
    assert plugin.engine is not plugin.read_engine
    assert [engine.size for engine in engines] == [1, 2]
    release = threading.Event()
    reads = [asyncio.create_task(plugin.read(lambda: release.wait(3))) for _ in range(2)]
    stopping = queued = None
    try:
        await until(lambda: plugin.read_lane.active == 2)
        assert await asyncio.wait_for(plugin.control(lambda: "saved"), 1) == "saved"
        queued = asyncio.create_task(plugin.read(lambda: "drained"))
        await until(lambda: plugin.read_lane.pending == 3)
        stopping = asyncio.create_task(plugin.stop())
        await until(lambda: not plugin.read_lane.accepting)
        for _ in range(3):
            stopping.cancel()
            await asyncio.sleep(0)
            assert not stopping.done()
        with pytest.raises(RuntimeError, match="关闭"):
            await plugin.control(lambda: None)
        assert all(not engine.dispose.called for engine in engines)
        release.set()
        assert await queued == "drained"
        with pytest.raises(asyncio.CancelledError):
            await stopping
        assert all(engine.dispose.call_count == 1 for engine in engines)
        assert plugin.engine is plugin.read_engine is None
        await plugin.stop()
        await plugin.start(None)
        assert await plugin.read(lambda: "restarted") == "restarted"
    finally:
        release.set()
        await asyncio.gather(*reads, *([queued] if queued else []),
                             *([stopping] if stopping else []), return_exceptions=True)
        await plugin.stop()
    assert not any(t.name.startswith("empire-mysql-") for t in threading.enumerate())


async def test_failed_start_disposes_both_pools(monkeypatch):
    engines = []

    def factory(*args, **kwargs):
        engine = MagicMock()
        engines.append(engine)
        return engine

    def invalid(self):
        raise RuntimeError("missing schema")

    monkeypatch.setattr("empire.plugins.infra.mysql_store.make_engine", factory)
    monkeypatch.setattr(MySQLPlugin, "_validate", invalid)
    plugin = MySQLPlugin({"database": "test"})
    with pytest.raises(RuntimeError, match="missing schema"):
        await plugin.start(None)
    assert all(engine.dispose.call_count == 1 for engine in engines)
    assert plugin.engine is plugin.read_lane is plugin.control_lane is None
