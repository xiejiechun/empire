"""Real Redis retention and race-safe cleanup; UUID-owned keys only."""
import json
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest

from empire.contracts.plugin import PluginContext
from empire.core.config import load_config
from empire.core.manager import Registry
from empire.core.redaction import Redactor
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
    await service.start(PluginContext("collection.records", registry, sanitize_error=Redactor.from_config(cfg).text))
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
    reviewed = []
    for offset in range(0, 300, 100):
        reviewed.extend((await records.list_error_summaries("stocks", offset, 100))["rows"])
    assert len(reviewed) == 300
    assert reviewed[0]["id"] == "stocks-304"
    assert reviewed[-1]["id"] == "stocks-5"
    # A failure arrives while the selected failures are being investigated and fixed.
    await records.add_error("stocks", stage="parse", error="new unrelated failure", record_id="new")
    selected = [row["id"] for row in reviewed[:3]]
    assert await records.clear_errors("stocks", selected) == 3
    remaining = (await records.list_error_summaries("stocks", 0, 100))["rows"]
    assert remaining[0]["id"] == "new"
    assert not set(selected) & {row["id"] for row in remaining}
    assert (await records.list_error_summaries("news"))["total"] == 300
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
    page = await records.list_error_summaries("stocks")
    assert page["total"] == 1 and "body" not in page["rows"][0]
    row = await records.get_error("stocks", "retry-id")
    assert row["body_truncated"]
    assert len(row["body"].encode()) <= 65536
    assert row["original_bytes"] == 70000
    assert "synthetic-password" not in str(row)
    assert "hidden" not in row["request_url"]
    assert await records.clear_errors("stocks", ["retry-id"]) == 1
    assert not (await records.list_error_summaries("stocks"))["total"]


async def test_full_large_error_set_transfers_summaries_then_one_detail(records):
    body = "x" * (64 * 1024)
    values = [json.dumps({"id": f"large-{number}", "project_id": "large",
              "created_at": "2026-09-26T00:00:00+00:00", "version": "test",
              "stage": "download", "error": f"failure {number}", "request_url": "",
              "status_code": 503, "metadata": {}, "body": body, "body_truncated": True,
              "body_complete": True, "observed_bytes": len(body), "original_bytes": len(body),
              "original_sha256": "a" * 64, "sample_sha256": "b" * 64},
              separators=(",", ":")) for number in range(300)]
    key = records._key("errors", "large")
    revision = records._revision_key("errors", "large")
    for start in range(0, len(values), 25):
        await records.redis.client.rpush(key, *values[start:start + 25])
    await records.redis.client.set(revision, "1")
    page = await records.list_error_summaries("large", 0, 50)
    encoded = json.dumps(page)
    assert page["total"] == 300 and len(page["rows"]) == 50
    assert "body" not in encoded and len(encoded.encode()) < 20000
    unchanged = await records.list_error_summaries("large", 0, 50, page["revision"])
    assert not unchanged["changed"] and unchanged["rows"] == []
    assert len(json.dumps(unchanged).encode()) < 200
    detail = await records.get_error("large", "large-20")
    assert len(detail["body"]) == 64 * 1024
