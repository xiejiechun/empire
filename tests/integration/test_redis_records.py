"""Real Redis retention and race-safe cleanup; UUID-owned keys only."""
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from empire.contracts.plugin import PluginContext
from empire.core.config import load_config
from empire.core.manager import Registry
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.infra.redis_store import create_client

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly"
)]


@pytest.fixture
async def records():
    cfg = load_config()
    prefix = "empire:test:" + uuid4().hex
    client = create_client(cfg["redis"])
    registry = Registry()
    registry.values["redis.store"] = SimpleNamespace(client=client, prefix=prefix)
    service = RecordsPlugin(secrets=("synthetic-password",))
    await service.start(PluginContext("collection.records", registry))
    try:
        yield service
    finally:
        keys = [key async for key in client.scan_iter(match=prefix + ":*")]
        if keys:
            assert all(key.startswith(prefix + ":") for key in keys)
            await client.delete(*keys)
        await service.stop()
        await client.aclose()


async def test_each_project_has_independent_limits_and_clear_keeps_new_errors(records):
    for project in ("stocks", "news"):
        for number in range(305):
            await records.add_error(project, stage="parse", error=f"error {number}",
                                    raw_body="sample", record_id=f"{project}-{number}")
        for number in range(105):
            await records.add_archive(project, {"id": f"archive-{number}", "status": "complete"})
    reviewed = await records.list_errors("stocks")
    assert len(reviewed) == 300
    assert reviewed[0]["id"] == "stocks-304"
    assert reviewed[-1]["id"] == "stocks-5"
    # A failure arrives while the selected failures are being investigated and fixed.
    await records.add_error("stocks", stage="parse", error="new unrelated failure", record_id="new")
    selected = [row["id"] for row in reviewed[:3]]
    assert await records.clear_errors("stocks", selected) == 3
    remaining = await records.list_errors("stocks")
    assert remaining[0]["id"] == "new"
    assert not set(selected) & {row["id"] for row in remaining}
    assert len(await records.list_errors("news")) == 300
    for project in ("stocks", "news"):
        history = await records.list_archives(project)
        assert len(history) == 100
        assert history[-1]["id"] == "archive-5"
    assert await records.redis.client.xlen(records.redis.prefix + ":ingest") == 0


async def test_error_redaction_and_idempotent_retry_are_persisted(records):
    fields = {"stage": "parse", "error": "password=synthetic-password",
              "raw_body": b'x' * 70000, "record_id": "retry-id",
              "request_url": "https://user:synthetic-password@example.org/?token=hidden"}
    await records.add_error("stocks", **fields)
    await records.add_error("stocks", **fields)
    rows = await records.list_errors("stocks")
    assert len(rows) == 1
    assert rows[0]["body_truncated"]
    assert len(rows[0]["body"].encode()) <= 65536
    assert rows[0]["original_bytes"] == 70000
    assert "synthetic-password" not in str(rows)
    assert "hidden" not in rows[0]["request_url"]
    assert await records.clear_errors("stocks", ["retry-id"]) == 1
    assert await records.list_errors("stocks") == []
