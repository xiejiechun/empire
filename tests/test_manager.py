import asyncio

import pytest

from empire.contracts.plugin import PluginManifest
from empire.core.manager import DependencyError, PluginManager


class Stub:
    def __init__(self, name, *, requires=(), fail=False, trace=None):
        self.manifest = PluginManifest(name, name, requires=requires, provides=(name,))
        self.fail = fail
        self.trace = trace if trace is not None else []

    async def start(self, context):
        self.trace.append("start:" + self.manifest.id)
        if self.fail:
            raise RuntimeError("unavailable")
        return {self.manifest.id: self}

    async def stop(self):
        self.trace.append("stop:" + self.manifest.id)

    def health(self):
        return {"ok": True}


async def test_dependency_order_and_stop_guard():
    trace = []
    manager = PluginManager([
        Stub("collector", requires=("archive",), trace=trace),
        Stub("archive", requires=("redis",), trace=trace),
        Stub("redis", trace=trace),
    ])
    await manager.start("collector")
    assert trace == ["start:redis", "start:archive", "start:collector"]
    with pytest.raises(DependencyError, match="archive"):
        await manager.stop("redis")
    assert manager.entries["redis"].state == "RUNNING"
    await manager.stop("redis", cascade=True)
    assert trace[-3:] == ["stop:collector", "stop:archive", "stop:redis"]
    assert not manager.registry.values


async def test_dependency_failure_never_starts_collector():
    downstream = Stub("collector", requires=("database",))
    manager = PluginManager([downstream, Stub("database", fail=True)])
    with pytest.raises(DependencyError):
        await manager.start("collector")
    assert downstream.trace == []
    assert manager.entries["collector"].state == "BLOCKED"
    assert manager.entries["database"].state == "FAILED"
    assert not manager.registry.values


def test_cycles_and_ambiguous_providers_rejected():
    with pytest.raises(DependencyError, match="Circular"):
        PluginManager([Stub("a", requires=("b",)), Stub("b", requires=("a",))])
    with pytest.raises(DependencyError, match="missing"):
        PluginManager([Stub("a", requires=("missing",))])


async def test_stop_source_keeps_archive_running():
    manager = PluginManager([Stub("archive"), Stub("source", requires=("archive",))])
    await manager.start("source")
    await manager.stop("source")
    assert manager.entries["archive"].state == "RUNNING"
    await manager.shutdown()


async def test_owned_tasks_are_cancelled_before_stopped():
    finished = asyncio.Event()

    class Owner(Stub):
        async def start(self, context):
            async def work():
                try:
                    await asyncio.sleep(100)
                finally:
                    finished.set()
            context.spawn(work(), name="test")
            return {self.manifest.id: self}

    manager = PluginManager([Owner("worker")])
    await manager.start("worker")
    await asyncio.sleep(0)
    await manager.stop("worker")
    assert finished.is_set()
    assert manager.entries["worker"].context is None


async def test_failed_stop_prevents_duplicate_owner():
    class BrokenStop(Stub):
        async def stop(self):
            raise RuntimeError("resource did not exit")

    manager = PluginManager([BrokenStop("worker")])
    await manager.start("worker")
    with pytest.raises(RuntimeError):
        await manager.stop("worker")
    assert manager.entries["worker"].state == "FAILED"
    with pytest.raises(DependencyError, match="Stop incomplete"):
        await manager.start("worker")
