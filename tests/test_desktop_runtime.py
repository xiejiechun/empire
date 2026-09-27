import asyncio
import json
import time

import pytest

from empire.__main__ import acquire_instance_lock
from empire.contracts.plugin import PluginManifest
from empire.core.runtime import Runtime


def test_one_instance_lock_is_not_scoped_to_config_file(tmp_path, monkeypatch):
    monkeypatch.setattr("empire.__main__.user_data_dir", lambda: tmp_path)
    first = acquire_instance_lock()
    try:
        with pytest.raises(RuntimeError, match="已在当前用户下运行"):
            acquire_instance_lock()
    finally:
        first.unlock()
    second = acquire_instance_lock()
    second.unlock()


def test_runtime_bridge_stops_thread_and_persists_desired_state(tmp_path, monkeypatch):
    from empire.core.manager import PluginManager

    class MinimalPlugin:
        manifest = PluginManifest("test.plugin", "test", provides=("test",))

        async def start(self, context):
            assert asyncio.get_running_loop() is not None
            return {"test": self}

        async def stop(self):
            pass

        def health(self):
            return {"status": "ok"}

    monkeypatch.setattr("empire.core.runtime.user_data_dir", lambda: tmp_path)
    runtime = Runtime(lambda: PluginManager([MinimalPlugin()]), {})
    runtime.start()
    try:
        runtime.command("start", "test.plugin").result(timeout=5)
        assert '"test.plugin": true' in (tmp_path / "plugin-state.json").read_text()
        runtime.command("stop", "test.plugin").result(timeout=5)
        assert '"test.plugin": false' in (tmp_path / "plugin-state.json").read_text()
    finally:
        runtime.command("shutdown").result(timeout=5)
        runtime.thread.join(timeout=5)
    assert runtime.closed.is_set()
    assert not runtime.thread.is_alive()


@pytest.mark.parametrize("password", ['"', 'escaped"quote\\'])
def test_runtime_snapshot_redacts_values_without_breaking_json(tmp_path, monkeypatch, password):
    from empire.core.manager import PluginManager

    manager = PluginManager([])
    manager.snapshot = lambda: {"plugins": [], 'quoted"key': {"error": "failed " + password}}
    monkeypatch.setattr("empire.core.runtime.user_data_dir", lambda: tmp_path)
    runtime = Runtime(lambda: manager, {"mysql": {"password": password}})
    runtime.start()
    try:
        deadline = time.monotonic() + 3
        while 'quoted"key' not in runtime.snapshot() and time.monotonic() < deadline:
            time.sleep(.01)
        snapshot = runtime.snapshot()
        assert json.loads(json.dumps(snapshot))['quoted"key']["error"] == "failed [REDACTED]"
        assert not runtime.closed.is_set()
    finally:
        if not runtime.closed.is_set():
            runtime.command("shutdown").result(timeout=5)
        runtime.thread.join(timeout=5)


def test_unexpected_snapshot_failure_still_shuts_down_plugins(tmp_path, monkeypatch):
    from empire.core.manager import PluginManager

    class ResourcePlugin:
        manifest = PluginManifest("test.plugin", "test", provides=("test",), autostart=True)
        open = False
        stopped = False

        async def start(self, context):
            self.open = True
            return {"test": self}

        async def stop(self):
            self.open = False
            self.stopped = True

        def health(self):
            return {}

    plugin = ResourcePlugin()
    manager = PluginManager([plugin])
    snapshot = manager.snapshot

    def fail_after_start():
        if plugin.open:
            raise RuntimeError('snapshot failed: synthetic"password')
        return snapshot()

    manager.snapshot = fail_after_start
    monkeypatch.setattr("empire.core.runtime.user_data_dir", lambda: tmp_path)
    runtime = Runtime(lambda: manager, {"mysql": {"password": 'synthetic"password'}})
    runtime.start()
    runtime.thread.join(timeout=5)
    assert runtime.closed.is_set() and not runtime.thread.is_alive()
    assert plugin.stopped and not plugin.open
    assert manager.registry.values == {}
    assert runtime.snapshot()["error"] == "snapshot failed: [REDACTED]"
