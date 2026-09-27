import asyncio
import json
from datetime import datetime
from types import SimpleNamespace

import pytest

from empire.contracts.plugin import PluginContext
from empire.core.manager import Registry
from empire.core.redaction import Redactor
from empire.plugins.collection.control import (
    CHINA,
    CollectionControl,
    TaskContribution,
    next_due,
    retain_task_history,
    validate_policy,
)
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.settings import SettingsStore

POLICY = {"enabled": True, "mode": "manual", "interval_seconds": 300,
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


class MySQL:
    def __init__(self):
        self.data = {}
        self.fail = False

    async def control(self, operation, *args):
        if self.fail:
            raise ConnectionError("offline")
        if operation.__name__ == "_load":
            return dict(self.data.get(args[0], {}))
        kind, key, value = args
        self.data.setdefault(kind, {})[key] = dict(value)


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


async def setup(redis=None, mysql=None):
    redis = redis or Redis()
    mysql = mysql or MySQL()
    # Persist the supplied canonical policy before recovering runtime state.
    if not mysql.data and redis.data.get("test:collection:control:v1"):
        mysql.data["task"] = {key: validate_policy(job["policy"])
            for key, job in json.loads(redis.data["test:collection:control:v1"])["jobs"].items()}
    collector = Collector()
    http = HttpService(redis, "test", {"sina": {"domains": ["sina.com.cn"]}},
                       settings=SettingsStore(mysql, "test"))
    registry = Registry()
    registry.values.update({"mysql.store": mysql, "redis.store": SimpleNamespace(client=redis, prefix="test"),
                            "source": collector, "http.fetch": http,
                            "collection.records": RecordsPlugin(secrets=("example-password",))})
    control = CollectionControl([TaskContribution("stocks", "股票", "source", "sina", "列表")])
    await control.start(PluginContext("control", registry, sanitize_error=Redactor().text))
    return control, collector, redis, http


async def test_control_remains_available_when_one_collector_is_disabled():
    control, collector, _, _ = await setup()
    assert "source" not in control.manifest.requires
    registry = control.context.services
    registry.values.pop("source")
    snapshot = await control.workspace("tasks")
    assert snapshot["jobs"][0]["progress"] == {"status": "unavailable"}
    with pytest.raises(ValueError, match="未启用"):
        await control.run("stocks")
    registry.values["source"] = collector
    run_id = await control.run("stocks")
    assert run_id
    await control.pause("stocks")
    await control.stop()


def test_schedule_beijing_and_missed_days_coalesce():
    now = datetime(2026, 9, 22, 19, tzinfo=CHINA).timestamp()
    assert next_due(POLICY, now) is None
    daily = {**POLICY, "mode": "daily"}
    assert datetime.fromtimestamp(next_due(daily, now), CHINA).isoformat() == "2026-09-23T18:00:00+08:00"
    assert next_due({**POLICY, "mode": "interval"}, now) == now + 300
    assert next_due({**daily, "enabled": False}, now) is None


async def test_proxy_policy_is_snapshotted_for_run_and_does_not_leak_context():
    from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY

    control, collector, _, http = await setup()
    started, finish = asyncio.Event(), asyncio.Event()
    observed = []

    async def execute(**kwargs):
        observed.append((USE_PROXY.get(), PROXY_FALLBACK.get()))
        started.set()
        await finish.wait()
        observed.append((USE_PROXY.get(), PROXY_FALLBACK.get()))
        ROUTE_COUNTS.get()["proxy_requests"] = 3
        return {}

    collector.execute = execute
    try:
        await control.configure("stocks", {**POLICY, "use_proxy": True, "proxy_fallback": False})
        await control.run("stocks")
        await started.wait()
        await control.configure("stocks", {**POLICY, "use_proxy": False, "proxy_fallback": True})
        assert USE_PROXY.get() is False and ROUTE_COUNTS.get() is None
        finish.set()
        await control.tasks["stocks"]
        assert observed == [(True, False), (True, False)]
        assert control.state["history"][0]["network"] == {"proxy_requests": 3}
    finally:
        finish.set()
        await control.stop()
        await http.close()


@pytest.mark.parametrize("field,value", [("request_retries", 8), ("daily_time", "25:00"),
                                         ("interval_seconds", 0), ("enabled", "yes")])
def test_invalid_settings(field, value):
    with pytest.raises(ValueError):
        validate_policy({**POLICY, field: value})


@pytest.mark.parametrize("seconds", [1, 7, 59, 90, 2592000])
def test_second_intervals(seconds):
    policy = validate_policy({**POLICY, "mode": "interval", "interval_seconds": seconds})
    assert "interval_minutes" not in policy
    assert next_due(policy, 1000) == 1000 + seconds


@pytest.mark.parametrize("seconds", [0, -1, 2592001, True, 1.5, "30"])
def test_invalid_second_intervals(seconds):
    with pytest.raises(ValueError):
        validate_policy({**POLICY, "interval_seconds": seconds})


async def test_restart_preserves_existing_due_time():
    redis = Redis()
    redis.data["test:collection:control:v1"] = json.dumps({"jobs": {"stocks": {
        "policy": {**POLICY, "mode": "interval"}, "next_due": 9999999999,
        "active": None, "last_status": "idle"}}, "history": []})
    control, source, _, http = await setup(redis)
    try:
        job = json.loads(redis.data[control.key])["jobs"]["stocks"]
        assert job["policy"]["interval_seconds"] == 300
        assert "interval_minutes" not in job["policy"]
        assert job["next_due"] == 9999999999
    finally:
        await control.stop()
        await http.close()


async def test_second_delay_is_measured_from_completion():
    control, source, redis, http = await setup()
    try:
        await control.configure("stocks", {**POLICY, "mode": "interval", "interval_seconds": 7})
        await control.run("stocks")
        source.gate.set()
        await control.tasks["stocks"]
        saved = json.loads(redis.data[control.key])
        assert saved["jobs"]["stocks"]["next_due"] == pytest.approx(
            saved["history"][0]["finished_at"] + 7, abs=.1)
        assert saved["jobs"]["stocks"]["policy"]["interval_seconds"] == 7
    finally:
        await control.stop()
        await http.close()


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
        history = (await control.workspace("history", project="stocks", limit=100))["history"]
        assert history[0]["run_id"] == "existing"
        assert history[0]["status"] == "complete"
    finally:
        await control.stop()
        await http.close()


async def test_failed_setting_write_rolls_back_and_site_group_updates_all_hosts():
    control, _, redis, http = await setup()
    try:
        control.settings.mysql.fail = True
        with pytest.raises(ConnectionError):
            await control.configure("stocks", {**POLICY, "enabled": False})
        assert control.state["jobs"]["stocks"]["policy"]["enabled"]
        with pytest.raises(ConnectionError):
            await http.configure_site("sina", {"min_interval_ms": 5000})
        assert http.rules.groups[0].min_interval_ms == 2000
        control.settings.mysql.fail = False
        await http.configure_site("sina", {"min_interval_ms": 5000})
        for host in ("finance.sina.com.cn", "vip.stock.finance.sina.com.cn"):
            assert http.rules.resolve(f"https://{host}/", ("sina.com.cn",)).min_interval_ms == 5000
    finally:
        await control.stop()
        await http.close()


async def test_retired_full_snapshot_and_scalar_site_configuration_are_not_supported():
    control, _, _, http = await setup()
    try:
        assert not hasattr(control, "snapshot")
        assert not hasattr(http, "configure_interval")
        with pytest.raises(ValueError, match="完整策略"):
            await control.configure_site("sina", 5000)
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
        control.settings.mysql.fail = True
        with pytest.raises(ConnectionError):
            await control.configure("stocks", {**POLICY, "enabled": False})
        control.settings.mysql.fail = False
        source.gate.set()
        await control.tasks["stocks"]
        assert control.state["jobs"]["stocks"]["active"] is None
        assert control.state["jobs"]["stocks"]["last_status"] == "complete"
        assert len(control.state["history"]) == 1
    finally:
        await control.stop()
        await http.close()


async def test_mysql_settings_survive_empty_redis_and_override_stale_cache():
    mysql = MySQL()
    control, _, redis, http = await setup(mysql=mysql)
    policy = validate_policy({**POLICY, "mode": "interval", "interval_seconds": 700})
    try:
        await control.configure("stocks", policy)
        await http.configure_site("sina", {"min_interval_ms": 4200})
    finally:
        await control.stop()
        await http.close()
    control, source, _, http = await setup(Redis(), mysql)
    try:
        assert control.state["jobs"]["stocks"]["policy"] == policy
        assert control.state["jobs"]["stocks"]["next_due"] is not None
        assert not source.calls
        assert mysql.data["site"]["sina"] == {"min_interval_ms": 4200,
            "proxy_interval_ms": 2000, "total_interval_ms": 500, "max_concurrency": 1,
            "scaling_mode": "fixed", "max_rps": 0}
    finally:
        await control.stop()
        await http.close()


async def test_sql_commit_remains_authoritative_when_redis_sync_fails():
    control, _, redis, http = await setup()
    try:
        redis.fail = True
        message = await control.configure("stocks", {**POLICY, "enabled": False})
        assert "MySQL" in message and "同步失败" in message
        assert not control.state["jobs"]["stocks"]["policy"]["enabled"]
        assert not control.settings.mysql.data["task"]["stocks"]["enabled"]
    finally:
        redis.fail = False
        await control.stop()
        await http.close()


async def test_mysql_policy_wins_over_stale_redis_and_reschedules():
    mysql, redis = MySQL(), Redis()
    mysql.data["task"] = {"stocks": validate_policy({**POLICY, "enabled": False})}
    redis.data["test:collection:control:v1"] = json.dumps({"jobs": {"stocks": {
        "policy": {**POLICY, "mode": "interval"}, "next_due": 1,
        "active": None, "last_status": "idle"}}, "history": []})
    control, source, _, http = await setup(redis, mysql)
    try:
        await asyncio.sleep(0)
        assert not control.state["jobs"]["stocks"]["policy"]["enabled"]
        assert control.state["jobs"]["stocks"]["next_due"] is None
        assert not source.calls
    finally:
        await control.stop()
        await http.close()
