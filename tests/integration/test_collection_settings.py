import copy
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.core.config import load_config
from empire.plugins.infra.settings import SettingsStore

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly"
)]


async def test_mysql_settings_survive_loss_of_redis_runtime_without_collection():
    cfg = copy.deepcopy(load_config())
    cfg["redis"]["namespace"] = "empire:test:" + uuid4().hex
    manager = build_manager(cfg)
    try:
        await manager.start("collection.control")
        control = manager.registry.get("collection.control")
        data = await control.workspace("tasks")
        policy = {**data["jobs"][0]["policy"], "mode": "daily", "daily_time": "18:30",
                  "use_proxy": True, "proxy_fallback": True}
        site_policy = {"min_interval_ms": 4100, "proxy_interval_ms": 2100,
                       "total_interval_ms": 600, "max_concurrency": 64,
                       "scaling_mode": "auto", "max_rps": 20}
        await control.configure("sina-stocks", policy)
        await control.configure_site("sina", site_policy)
        original_due = control.state["jobs"]["sina-stocks"]["next_due"]
        mysql = manager.registry.get("mysql.store")
        statements = []

        def capture(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
                statements.append(statement)

        event.listen(mysql.engine, "before_cursor_execute", capture)
        try:
            await SettingsStore(mysql, cfg["redis"]["namespace"]).save("task", "sina-stocks", policy)
            await control.configure_site("sina", site_policy)
            assert statements == []
        finally:
            event.remove(mysql.engine, "before_cursor_execute", capture)
        await manager.stop("collection.control")
        await manager.start("collection.control")
        assert manager.registry.get("collection.control").state["jobs"]["sina-stocks"]["next_due"] == original_due
        await manager.stop("infra.http", cascade=True)
        store = manager.registry.get("redis.store")
        await store.client.delete(f"{store.prefix}:collection:control:v1")
        await manager.start("collection.control")
        control = manager.registry.get("collection.control")
        tasks = await control.workspace("tasks")
        sites = await control.workspace("sites")
        history = await control.workspace("history")
        assert tasks["jobs"][0]["policy"] == policy
        assert tasks["jobs"][0]["next_due"]
        assert tasks["jobs"][0]["active"] is None
        assert next(s for s in sites["sites"] if s["name"] == "sina")["min_interval_ms"] == 4100
        saved_site = next(s for s in sites["sites"] if s["name"] == "sina")
        assert all(saved_site[k] == v for k, v in site_policy.items())
        assert history["history"] == []
    finally:
        await manager.stop("collection.control")
        await manager.stop("pipeline.archive", cascade=True)
        store = manager.registry.get("redis.store")
        await store.client.delete(f"{store.prefix}:collection:control:v1",
            f"{store.prefix}:collection:site-intervals:v1", store.stream)
        mysql = manager.registry.get("mysql.store")
        with mysql.engine.begin() as conn:
            conn.execute(text("DELETE FROM app_setting WHERE namespace=:namespace"),
                         {"namespace": cfg["redis"]["namespace"]})
        await manager.shutdown()


async def test_project_history_is_bounded_in_redis_and_never_enqueued():
    cfg = copy.deepcopy(load_config())
    cfg["redis"]["namespace"] = "empire:test:" + uuid4().hex
    manager = build_manager(cfg)
    try:
        await manager.start("collection.control")
        await manager.start("pipeline.archive")
        control = manager.registry.get("collection.control")
        store = manager.registry.get("redis.store")
        control.state["history"] = [
            {"task_id": ident, "run_id": f"{ident}:{number}", "finished_at": number,
             "started_at": number - 1, "status": "complete", "result": {}, "error": ""}
            for ident in ("test-stocks", "test-news") for number in range(125)]
        await control._persist()
        saved = json.loads(await store.client.get(control.key))
        for ident in ("test-stocks", "test-news"):
            records = [r for r in saved["history"] if r["task_id"] == ident]
            assert len(records) == 100
            assert min(r["finished_at"] for r in records) == 25
        assert await store.client.xlen(store.stream) == 0
        await manager.registry.get("archive.worker").flush()
        assert json.loads(await store.client.get(control.key))["history"] == saved["history"]
        assert await store.client.xlen(store.stream) == 0
    finally:
        await manager.stop("collection.control")
        await manager.stop("pipeline.archive", cascade=True)
        store = manager.registry.get("redis.store")
        await store.client.delete(f"{store.prefix}:collection:control:v1", store.stream)
        await manager.shutdown()
