"""UUID-scoped settings only; never starts collectors or alters business tables."""
import copy
import json
import os
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.bootstrap import build_manager
from empire.contracts.download import MiB
from empire.contracts.download_settings import DEFAULTS
from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Explicit integration opt-in required")]


@pytest.fixture
async def environment(tmp_path):
    cfg = copy.deepcopy(load_config())
    namespace = "empire:test:download-settings:" + uuid4().hex
    cfg["redis"]["namespace"] = namespace
    cfg["http"] = {"download_directory": str(tmp_path / "downloads")}
    managers = []
    marker = namespace + ":test-volatile-marker"
    try:
        yield cfg, managers, marker
    finally:
        for manager in reversed(managers):
            await manager.shutdown()
        engine = make_engine(cfg["mysql"])
        client = create_client(cfg["redis"])
        try:
            # Exact test-owned namespace/key only. No business or producer key deletion.
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM app_setting WHERE namespace=:namespace "
                    "AND kind='download' AND setting_key='global'"), {"namespace": namespace})
            await client.delete(marker)
        finally:
            engine.dispose()
            await client.aclose()


async def start_http(cfg, managers):
    manager = build_manager(cfg)
    managers.append(manager)
    await manager.start("infra.http")
    assert all(entry.state == "STOPPED" for entry in manager.entries.values()
               if entry.plugin.manifest.id.startswith("collector."))
    assert manager.entries["collection.control"].state == "STOPPED"
    assert manager.entries["pipeline.archive"].state == "STOPPED"
    return manager


async def test_same_download_settings_skip_sql_dml_and_keep_one_global_row(environment):
    cfg, managers, _ = environment
    manager = await start_http(cfg, managers)
    service = manager.registry.get("download.settings")
    mysql = manager.registry.get("mysql.store")
    values = {**DEFAULTS, "buffer_budget_bytes": 96 * MiB,
              "stock_response_bytes": 2 * MiB, "file_response_bytes": 128 * MiB}
    await service.save(values)
    statements = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(statement)

    event.listen(mysql.engine, "before_cursor_execute", capture)
    try:
        await service.save(dict(values))
        assert statements == []
    finally:
        event.remove(mysql.engine, "before_cursor_execute", capture)
    with mysql.engine.connect() as conn:
        rows = conn.execute(text("SELECT kind,setting_key,payload FROM app_setting "
            "WHERE namespace=:namespace"), {"namespace": cfg["redis"]["namespace"]}).all()
    assert len(rows) == 1 and tuple(rows[0][:2]) == ("download", "global")
    stored = json.loads(rows[0][2]) if isinstance(rows[0][2], str) else rows[0][2]
    assert stored == values


async def test_saved_limits_survive_runtime_restart_and_loss_of_test_redis_state(environment):
    cfg, managers, marker = environment
    first = await start_http(cfg, managers)
    settings = first.registry.get("download.settings")
    current_http = first.registry.get("http.fetch")
    values = {**DEFAULTS, "buffer_budget_bytes": 128 * MiB,
              "stock_response_bytes": 3 * MiB, "news_response_bytes": 6 * MiB,
              "calendar_response_bytes": MiB, "generic_response_bytes": 4 * MiB,
              "file_response_bytes": 64 * MiB, "download_quota_bytes": 512 * MiB,
              "disk_free_margin_bytes": 32 * MiB, "file_concurrency": 2}
    saved = await settings.save(values)
    assert saved["pending_restart"] is True
    assert current_http.buffer_budget.limit == DEFAULTS["buffer_budget_bytes"]
    redis = first.registry.get("redis.store").client
    await redis.set(marker, "temporary state")
    await redis.delete(marker)  # Simulated loss only; never restart or clear shared Redis.
    assert not await redis.exists(marker)
    await first.shutdown()

    second = await start_http(cfg, managers)
    reloaded = second.registry.get("download.settings")
    http = second.registry.get("http.fetch")
    assert await reloaded.snapshot() == {"saved": values, "active": values, "pending_restart": False}
    assert http.buffer_budget.limit == 128 * MiB
    assert http.response_policy("stocks").max_body_bytes == 3 * MiB
    assert http.response_policy("news").max_body_bytes == 6 * MiB
    assert http.response_policy("calendar").max_body_bytes == MiB
    assert http.response_policy("generic").max_body_bytes == 4 * MiB
    assert http.file_policy(filename="test.pdf").max_body_bytes == 64 * MiB
    assert http.storage.quota == 512 * MiB
    assert http.storage.min_free == 32 * MiB and http.storage.concurrency == 2
    assert not http.storage.root.exists()  # Starting the service does not create/download files.
