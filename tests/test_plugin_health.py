"""Fault injection for resident task ownership, safe diagnostics and UI state."""
import asyncio
import json
import logging
import os
from types import SimpleNamespace

import pytest

from empire.contracts.plugin import PluginContext, PluginManifest
from empire.core.manager import DependencyError, PluginManager, Registry
from empire.core.redaction import Redactor


class Worker:
    def __init__(self, ident="worker", *, requires=(), outcome="wait", critical=True):
        self.manifest = PluginManifest(ident, ident, requires=requires, provides=(ident,))
        self.outcome, self.critical = outcome, critical
        self.release = asyncio.Event()
        self.started = 0
        self.health_value = {"status": "ok"}

    async def start(self, context):
        self.context = context
        self.started += 1

        async def run():
            await self.release.wait()
            if self.outcome == "raise":
                raise RuntimeError("password=hidden https://user:secret@host/\nplain-config-secret")

        self.task = context.spawn(run(), name="resident", critical=self.critical)
        if self.outcome == "startup":
            self.release.set()
            await asyncio.sleep(0)
        return {self.manifest.id: self}

    async def stop(self):
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)

    def health(self):
        if isinstance(self.health_value, Exception):
            raise self.health_value
        return dict(self.health_value)


def by_id(manager):
    return {p["id"]: p for p in manager.snapshot()["plugins"]}


@pytest.mark.parametrize("outcome", ["return", "raise", "cancel"])
async def test_critical_exit_fails_owner_and_degrades_dependencies_without_restarting(outcome):
    worker = Worker(outcome=outcome)
    middle = Worker("middle", requires=("worker",))
    leaf = Worker("leaf", requires=("middle",))
    extra = Worker("extra", requires=("middle",))
    manager = PluginManager([worker, middle, leaf, extra],
                            redactor=Redactor(("plain-config-secret",)))
    await manager.start("leaf")
    try:
        if outcome == "cancel":
            worker.task.cancel()
        else:
            worker.release.set()
        # Task has finished but its done callback has not necessarily run yet.
        await asyncio.sleep(0)
        data = by_id(manager)
        assert manager.entries["worker"].state == "FAILED"
        assert data["worker"]["state"] == "FAILED"
        assert data["middle"]["state"] == data["leaf"]["state"] == "DEGRADED"
        assert data["worker"]["can_start"] is False
        assert data["worker"]["health"]["background_tasks"]["critical_active"] == 0
        assert worker.context.tasks == set()
        assert worker.context.critical_failures == 1
        assert worker.started == 1
        serialized = json.dumps(data)
        for secret in ("plain-config-secret", "password=hidden", "user:secret"):
            assert secret not in serialized
        with pytest.raises(DependencyError):
            await manager.start("extra")
        assert extra.started == 0
        with pytest.raises(DependencyError, match="Stop incomplete"):
            await manager.start("worker")
        # Ownership remains until explicit normal stop; no automatic service restart.
        assert manager.registry.get("worker") is worker
    finally:
        await manager.shutdown()
    assert not manager.registry.values
    assert worker.context.stopping is True


async def test_critical_exit_during_start_cannot_be_overwritten_by_running():
    worker = Worker(outcome="startup")
    manager = PluginManager([worker])
    with pytest.raises(DependencyError, match="关键后台任务"):
        await manager.start("worker")
    assert manager.entries["worker"].state == "FAILED"
    assert manager.entries["worker"].context is None
    assert not manager.registry.values
    assert worker.context.critical_failures == 1


@pytest.mark.parametrize("complete", [False, True])
async def test_one_shot_completion_or_cancellation_is_not_a_health_failure(complete):
    worker = Worker(critical=False)
    manager = PluginManager([worker])
    await manager.start("worker")
    if complete:
        worker.release.set()
    else:
        worker.task.cancel()
    await asyncio.sleep(0)
    assert by_id(manager)["worker"]["state"] == "RUNNING"
    assert not worker.context.task_errors
    await manager.shutdown()


async def test_expected_stop_precedes_plugin_cancellation_and_restart_gets_fresh_health():
    worker = Worker()
    manager = PluginManager([worker])
    await manager.start("worker")
    await asyncio.sleep(0)
    await manager.stop("worker")
    assert not worker.context.task_errors
    assert worker.context.critical_failures == 0
    assert not worker.context.tasks
    await manager.start("worker")
    assert by_id(manager)["worker"]["state"] == "RUNNING"
    await manager.shutdown()


async def test_errors_are_bounded_sanitized_without_exception_or_task_retention(caplog):
    context = PluginContext("test", Registry(), sanitize_error=Redactor(("bare-secret",)).text)

    async def fail(number):
        raise RuntimeError(f"error {number} password=hidden bare-secret " + "测" * 3000)

    with caplog.at_level(logging.ERROR):
        await asyncio.gather(*(context.spawn(fail(i), name=f"job-{i}") for i in range(105)),
                             return_exceptions=True)
    context.reap_finished()
    assert context.error_count == 105
    assert len(context.task_errors) == 100
    assert "job-5" in context.task_errors[0]
    assert all(len(error.encode()) <= 2048 for error in context.task_errors)
    assert not context.tasks and not context._critical
    assert all(record.exc_info is None for record in caplog.records)
    assert "bare-secret" not in caplog.text and "password=hidden" not in caplog.text


async def test_exception_with_broken_string_conversion_does_not_break_done_callback():
    class BrokenError(Exception):
        def __str__(self):
            raise ValueError("cannot stringify")

    async def fail():
        raise BrokenError()

    context = PluginContext("test", Registry(), sanitize_error=Redactor().text)
    task = context.spawn(fail(), name="critical", critical=True)
    await asyncio.gather(task, return_exceptions=True)
    assert context.critical_failures == 1
    assert list(context.task_errors) == ["后台任务异常（错误详情无法安全格式化）"]


async def test_health_exception_and_transient_service_failure_are_visible_and_recoverable():
    worker = Worker()
    manager = PluginManager([worker])
    await manager.start("worker")
    try:
        for value in (RuntimeError("password=private"), {"status": "degraded", "error": "offline"},
                      {"status": "blocked"}):
            worker.health_value = value
            assert by_id(manager)["worker"]["state"] == "DEGRADED"
        worker.health_value = {"status": "ok"}
        assert by_id(manager)["worker"]["state"] == "RUNNING"
    finally:
        await manager.shutdown()


async def test_unhandled_one_shot_error_is_visible_but_does_not_fail_resident_owner():
    worker = Worker(outcome="raise", critical=False)
    manager = PluginManager([worker])
    await manager.start("worker")
    worker.release.set()
    await asyncio.sleep(0)
    assert by_id(manager)["worker"]["state"] == "DEGRADED"
    assert manager.entries["worker"].state == "RUNNING"
    assert worker.context.critical_failures == 0
    await manager.shutdown()


def test_system_pages_show_task_failure_and_require_normal_stop_before_restart():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.system import PluginsPage, SystemStatusPage

    app = QApplication.instance() or QApplication([])
    data = {"plugins": [{"id": "pipeline.archive", "name": "归档", "state": "FAILED",
                         "can_start": False, "enabled": True, "error": "后台任务意外退出",
                         "health": {}, "requires": []}]}
    shell = SimpleNamespace(runtime=SimpleNamespace(snapshot=lambda: data), cfg={},
                            command=lambda *args: None, navigate=lambda *args: None)
    plugins, system = PluginsPage(shell), SystemStatusPage(shell)
    try:
        assert plugins.table.item(0, 2).text() == "运行失败"
        assert not plugins.buttons["start"].isEnabled()
        assert plugins.buttons["stop"].isEnabled()
        assert "先正常停用" in plugins.description.text()
        assert system.values["archive"].text() == "运行失败"
        assert "意外退出" in system.issues.text()
        data["plugins"][0].update(state="DEGRADED", error="依赖服务异常")
        plugins.tick()
        system.tick()
        assert plugins.table.item(0, 2).text() == "运行异常"
        assert system.values["archive"].text() == "运行异常"
    finally:
        for page in (plugins, system):
            page.timer.stop()
            page.close()
            page.deleteLater()
        app.processEvents()
