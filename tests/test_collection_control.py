import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from empire.contracts.plugin import PluginContext
from empire.core.manager import Registry
from empire.plugins.collection.control import (
    CHINA,
    CollectionControl,
    CollectionTask,
    next_due,
    retain_task_history,
    validate_policy,
)
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.infra.http import HttpService

POLICY = {"enabled": True, "mode": "manual", "interval_minutes": 5,
          "daily_time": "18:00", "request_retries": 2}


class Redis:
    def __init__(self):
        self.data = {}
        self.fail = False

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value):
        if self.fail:
            raise ConnectionError("offline")
        self.data[key] = value


class Collector:
    def __init__(self):
        self.gate = asyncio.Event()
        self.calls = []

    async def checkpoint_revision(self):
        return 7

    async def execute(self, **kwargs):
        self.calls.append(kwargs)
        await self.gate.wait()
        return {"collected": 2}

    def health(self):
        return {"status": "idle"}


async def setup(redis=None):
    redis = redis or Redis()
    collector = Collector()
    http = HttpService(redis, "test", {"sina": {"domains": ["sina.com.cn"]}})
    registry = Registry()
    registry.values.update({"redis.store": SimpleNamespace(client=redis, prefix="test"),
                            "source": collector, "http.fetch": http,
                            "collection.records": RecordsPlugin(secrets=("example-password",))})
    control = CollectionControl([CollectionTask("stocks", "股票", "source", "sina", "列表")])
    await control.start(PluginContext("control", registry))
    return control, collector, redis, http


def test_schedule_beijing_and_missed_days_coalesce():
    now = datetime(2026, 9, 22, 19, tzinfo=CHINA).timestamp()
    assert next_due(POLICY, now) is None
    daily = {**POLICY, "mode": "daily"}
    assert datetime.fromtimestamp(next_due(daily, now), CHINA).isoformat() == "2026-09-23T18:00:00+08:00"
    assert next_due({**POLICY, "mode": "interval"}, now) == now + 300
    assert next_due({**daily, "enabled": False}, now) is None


@pytest.mark.parametrize("field,value", [("request_retries", 8), ("daily_time", "25:00"),
                                         ("interval_minutes", 0), ("enabled", "yes")])
def test_invalid_settings(field, value):
    with pytest.raises(ValueError):
        validate_policy({**POLICY, field: value})


async def test_no_implicit_collection_overlap_pause_and_saved_settings():
    control, source, redis, http = await setup()
    try:
        await asyncio.sleep(0)
        assert not source.calls
        await control.configure("stocks", {**POLICY, "mode": "interval"})
        await control.run("stocks")
        with pytest.raises(ValueError, match="重复"):
            await control.run("stocks")
        await asyncio.sleep(0)
        await control.pause("stocks")
        saved = json.loads(redis.data[control.key])
        assert not saved["jobs"]["stocks"]["policy"]["enabled"]
        assert saved["jobs"]["stocks"]["next_due"] is None
        assert saved["history"][0]["status"] == "paused"
        with pytest.raises(ValueError, match="禁用"):
            await control.run("stocks")
    finally:
        await control.stop()
        await http.close()


async def test_restart_recovers_same_run_and_baseline_then_records_completion():
    redis = Redis()
    redis.data["test:collection:control:v1"] = json.dumps({"jobs": {"stocks": {
        "policy": POLICY, "next_due": None, "last_status": "running",
        "active": {"run_id": "existing", "task_id": "stocks", "started_at": 1,
                   "origin": "manual", "fresh": True, "baseline_revision": 3}}}, "history": []})
    control, source, _, http = await setup(redis)
    try:
        source.gate.set()
        await asyncio.sleep(.03)
        assert source.calls == [{"fresh": True, "baseline_revision": 3}]
        history = (await control.snapshot())["history"]
        assert history[0]["run_id"] == "existing"
        assert history[0]["status"] == "complete"
    finally:
        await control.stop()
        await http.close()


async def test_failed_setting_write_rolls_back_and_site_group_updates_all_hosts():
    control, _, redis, http = await setup()
    try:
        redis.fail = True
        with pytest.raises(ConnectionError):
            await control.configure("stocks", {**POLICY, "enabled": False})
        assert control.state["jobs"]["stocks"]["policy"]["enabled"]
        with pytest.raises(ConnectionError):
            await http.configure_interval("sina", 5000)
        assert http.rules.groups[0].min_interval_ms == 2000
        redis.fail = False
        await http.configure_interval("sina", 5000)
        for host in ("finance.sina.com.cn", "vip.stock.finance.sina.com.cn"):
            assert http.rules.resolve(f"https://{host}/", ("sina.com.cn",)).min_interval_ms == 5000
    finally:
        await control.stop()
        await http.close()


async def test_pause_before_execution_coroutine_starts_clears_active_intent():
    control, _, _, http = await setup()
    try:
        await control.run("stocks")
        await control.pause("stocks")
        assert control.state["jobs"]["stocks"]["active"] is None
        assert control.state["history"][0]["status"] == "paused"
    finally:
        await control.stop()
        await http.close()


def test_history_keeps_each_projects_latest_100_independently():
    records = [{"task_id": task, "run_id": f"{task}:{i}", "finished_at": i}
               for task in ("stocks", "news") for i in range(130)]
    retained = retain_task_history(records)
    assert len(retained) == 200
    for task in ("stocks", "news"):
        own = [r for r in retained if r["task_id"] == task]
        assert [r["finished_at"] for r in own] == list(range(129, 29, -1))
    retained = retain_task_history([{"task_id": "stocks", "run_id": "new", "finished_at": 150}, *retained])
    assert len([r for r in retained if r["task_id"] == "news"]) == 100
    assert retained[0]["run_id"] == "new"


async def test_start_trims_existing_redis_history_without_discarding_other_projects():
    redis = Redis()
    redis.data["test:collection:control:v1"] = json.dumps({"jobs": {}, "history": [
        {"task_id": task, "finished_at": i} for task in ("stocks", "news") for i in range(105)]})
    control, _, _, http = await setup(redis)
    try:
        saved = json.loads(redis.data[control.key])
        assert len(saved["history"]) == 200
        assert min(r["finished_at"] for r in saved["history"]) == 5
    finally:
        await control.stop()
        await http.close()


async def test_failure_text_is_redacted_before_run_history_is_persisted():
    control, source, redis, http = await setup()

    async def fail(**kwargs):
        raise RuntimeError("request https://user:example-password@source.test/?token=private-token failed")

    source.execute = fail
    try:
        await control.run("stocks")
        await control.tasks["stocks"]
        saved = redis.data[control.key]
        assert "example-password" not in saved
        assert "private-token" not in saved
        assert control.state["history"][0]["status"] == "error"
        assert control.state["history"][0]["error"]
    finally:
        await control.stop()
        await http.close()


async def test_settings_rollback_during_running_task_does_not_leave_stale_active_state():
    control, source, redis, http = await setup()
    try:
        await control.run("stocks")
        await asyncio.sleep(0)
        redis.fail = True
        with pytest.raises(ConnectionError):
            await control.configure("stocks", {**POLICY, "enabled": False})
        redis.fail = False
        source.gate.set()
        await control.tasks["stocks"]
        assert control.state["jobs"]["stocks"]["active"] is None
        assert control.state["jobs"]["stocks"]["last_status"] == "complete"
        assert len(control.state["history"]) == 1
    finally:
        await control.stop()
        await http.close()
