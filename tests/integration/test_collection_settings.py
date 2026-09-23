import copy
import json
import os
from uuid import uuid4

import pytest

from empire.bootstrap import build_manager
from empire.core.config import load_config

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly"
)]


async def test_real_redis_settings_survive_plugin_restart_without_collection():
    cfg = copy.deepcopy(load_config())
    cfg["redis"]["namespace"] = "empire:test:" + uuid4().hex
    manager = build_manager(cfg)
    try:
        await manager.start("collection.control")
        control = manager.registry.get("collection.control")
        data = await control.snapshot()
        policy = {**data["jobs"][0]["policy"], "mode": "daily", "daily_time": "18:30"}
        await control.configure("sina-stocks", policy)
        await control.configure_site("sina", 4100)
        await manager.stop("infra.http", cascade=True)
        await manager.start("collection.control")
        result = await manager.registry.get("collection.control").snapshot()
        assert result["jobs"][0]["policy"] == policy
        assert result["jobs"][0]["next_due"]
        assert result["jobs"][0]["active"] is None
        assert next(s for s in result["sites"] if s["name"] == "sina")["min_interval_ms"] == 4100
        assert result["history"] == []
    finally:
        await manager.stop("collection.control")
        await manager.stop("pipeline.archive", cascade=True)
        store = manager.registry.get("redis.store")
        await store.client.delete(f"{store.prefix}:collection:control:v1",
            f"{store.prefix}:collection:site-intervals:v1", store.stream)
        await manager.shutdown()


async def test_project_history_is_bounded_in_redis_and_never_enqueued():
    cfg = copy.deepcopy(load_config())
    cfg["redis"]["namespace"] = "empire:test:" + uuid4().hex
    manager = build_manager(cfg)
    try:
        await manager.start("collection.control")
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
