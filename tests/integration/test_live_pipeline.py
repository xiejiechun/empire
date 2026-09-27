"""Opt-in tests against configured services; only UUID-owned keys/rows are cleaned."""
import asyncio
import copy
import os
import subprocess
import sys
import time
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_DNS, uuid4, uuid5

import httpx
import pytest
from sqlalchemy import text

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginContext
from empire.core.config import load_config
from empire.core.manager import Registry
from empire.core.redaction import Redactor
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.datasets.astock import DatasetPlugin
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.mysql_store import MySQLPlugin
from empire.plugins.infra.redis_store import RedisPlugin
from empire.plugins.pipeline.archive import ArchivePlugin
from empire.plugins.pipeline.ingest import BackpressureError, IngestPlugin, StaleCheckpointError

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Set EMPIRE_INTEGRATION=1 explicitly"
)]


@pytest.fixture
async def live():
    cfg = copy.deepcopy(load_config(os.environ.get("EMPIRE_CONFIG")))
    token = uuid4().hex
    cfg["redis"]["namespace"] = f"empire:test:{token}"
    redis = RedisPlugin(cfg["redis"])
    mysql = MySQLPlugin(cfg["mysql"])
    catalog = DatasetPlugin()
    archive = ArchivePlugin({"interval_seconds": 3600, "batch_size": 20})
    ingest = IngestPlugin(cfg["ingest"])
    registry = Registry()
    redactor = Redactor.from_config(cfg)
    contexts = []

    def context(ident):
        result = PluginContext(ident, registry, sanitize_error=redactor.text)
        contexts.append(result)
        return result
    records = RecordsPlugin()
    plugins = [catalog, redis, mysql, records]
    started = []
    ids = []
    snapshots = {}
    started_at = datetime.now(UTC).isoformat()
    try:
        for plugin in plugins:
            registry.values.update(await plugin.start(context(plugin.manifest.id)))
            started.append(plugin)
        registry.values["archive.worker"] = archive
        registry.values.update(await ingest.start(context("pipeline.ingest")))
        started.append(ingest)

        def event(sequence):
            snapshot_id = uuid5(NAMESPACE_DNS, f"{token}:{sequence}").hex
            base = {"snapshot_id": snapshot_id, "started_at": started_at,
                    "expected_count": 1, "page_size": 80, "node": "hs_a"}
            values = []
            for kind, extra in (("start", {"count_before": 1}),
                                ("page", {"page": 1, "rows": [
                                    {"symbol": "sz000001", "code": "000001", "name": "测试"}]}),
                                ("complete", {"pages": 1, "collected": 1, "count_after": 1,
                                              "terminal_rows": []})):
                value = make_envelope(
                    source=f"test-{token}", dataset=f"stock.universe.{kind}",
                    business_key=f"{snapshot_id}:{kind}", job_key="test", run_id=token,
                    batch_id=snapshot_id, payload={**base, **extra},
                )
                snapshots[value.event_id] = snapshot_id
                ids.append(value.event_id)
                values.append(value)
            return values

        async def start_archive():
            await archive.start(context("pipeline.archive"))
            started.append(archive)
            # Wait until its startup flush has finished before explicit failure injection.
            await asyncio.sleep(.05)
            await archive.flush()

        def count(event_id):
            with mysql.engine.connect() as conn:
                return conn.execute(text("SELECT COUNT(*) FROM collection_state WHERE source=:source "
                                    "AND JSON_UNQUOTE(JSON_EXTRACT(payload,'$.publication.snapshot_id'))=:id"),
                                    {"source": f"test-{token}", "id": snapshots[event_id]}).scalar_one()

        yield redis, mysql, archive, ingest, event, start_archive, count, registry
    finally:
        for owned in contexts:
            owned.begin_stop()
        if archive in started:
            await archive.stop()
        if mysql.engine:
            def clean_rows():
                with mysql.engine.begin() as conn:
                    conn.execute(text("DELETE FROM stock WHERE source=:source"),
                                 {"source": f"test-{token}"})
                    conn.execute(text("DELETE FROM collection_state WHERE source=:source"),
                                 {"source": f"test-{token}"})
            await mysql.control(clean_rows)
        if redis.client:
            keys = [key async for key in redis.client.scan_iter(f"{redis.prefix}:*")]
            if keys:
                await redis.client.delete(*keys)
        for plugin in reversed(started):
            if plugin is not archive:
                await plugin.stop()


async def test_preexisting_message_and_checkpoint_are_archived(live):
    redis, mysql, archive, ingest, event, start, count, _ = live
    value = event(1)
    await ingest.publish_page(value, job_key="test", expected_revision=0, cursor={"page": 1})
    assert await redis.client.xlen(redis.stream) == 3
    assert await ingest.checkpoint("test") == {"revision": 1, "cursor": {"page": 1}}
    await start()
    assert await redis.client.xlen(redis.stream) == 0
    assert await mysql.control(count, value[0].event_id) == 1


async def test_commit_before_ack_failure_replays_without_duplicates(live):
    redis, mysql, archive, ingest, event, start, count, _ = live
    await start()
    value = event(1)
    await ingest.publish_page(value, job_key="test", expected_revision=0, cursor={"page": 1})
    real_ack = archive.acknowledge

    async def failed_ack(ids):
        raise ConnectionError("Injected connection loss after MySQL commit")

    archive.acknowledge = failed_ack
    with pytest.raises(ConnectionError):
        await archive.flush()
    assert await mysql.control(count, value[0].event_id) == 1
    assert await redis.client.xlen(redis.stream) == 3
    assert await redis.client.xinfo_groups(redis.stream) == []
    archive.acknowledge = real_ack
    await archive.flush()
    assert await mysql.control(count, value[0].event_id) == 1
    assert await redis.client.xlen(redis.stream) == 0
    assert await redis.client.xinfo_groups(redis.stream) == []


async def test_stale_checkpoint_cannot_advance_or_enqueue(live):
    redis, _, _, ingest, event, _, _, _ = live
    await ingest.publish_page(event(1), job_key="test", expected_revision=0, cursor={"page": 1})
    with pytest.raises(StaleCheckpointError):
        await ingest.publish_page(event(2), job_key="test", expected_revision=0, cursor={"page": 2})
    assert await redis.client.xlen(redis.stream) == 3
    assert (await ingest.checkpoint("test"))["cursor"] == {"page": 1}


async def test_invalid_record_is_durably_recorded_in_redis_before_delete(live):
    redis, _, archive, _, _, start, _, registry = live
    await start()
    stream_id = await redis.client.xadd(redis.stream, {"envelope": "{invalid JSON"})
    await archive.flush()
    records = registry.get("collection.records")
    errors = await records.list_error_summaries("unknown")
    assert errors["total"] == 1
    assert (await records.get_error("unknown", errors["rows"][0]["id"]))["metadata"]["stream_id"] == stream_id
    assert await redis.client.xlen(redis.stream) == 0


async def test_mysql_failure_preserves_pending_data(live):
    redis, mysql, archive, ingest, event, start, count, _ = live
    await start()
    value = event(1)
    await ingest.publish_page(value, job_key="test", expected_revision=0, cursor={"page": 1})
    original = mysql.archive

    async def fail(records):
        raise ConnectionError("Injected MySQL outage")
    mysql.archive = fail
    with pytest.raises(ConnectionError):
        await archive.flush()
    assert await redis.client.xlen(redis.stream) == 3
    assert await mysql.control(count, value[0].event_id) == 0
    mysql.archive = original
    await archive.flush()
    assert await mysql.control(count, value[0].event_id) == 1


async def test_real_redis_limiter_is_shared_between_hosts(live):
    redis, *_ = live
    starts = []

    async def respond(request):
        starts.append(time.monotonic())
        return httpx.Response(200)

    service = HttpService(redis.client, redis.prefix, {
        "sina": {"domains": ["sina.com.cn"], "min_interval_ms": 50, "max_concurrency": 1}
    }, transport=httpx.MockTransport(respond))
    async def consume(host):
        response = await service.request("GET", f"https://{host}/", allowed_domains=("sina.com.cn",))
        response.close()

    try:
        await asyncio.gather(*[
            consume(host)
            for host in ("finance.sina.com.cn", "vip.stock.finance.sina.com.cn", "finance.sina.com.cn")
        ])
        assert len(starts) == 3
        assert all(b - a >= .040 for a, b in zip(starts, starts[1:]))
    finally:
        await service.close()


async def test_process_crash_after_commit_recovers_on_restart(live, tmp_path):
    redis, mysql, archive, ingest, event, start, count, _ = live
    await start()
    await archive.stop()
    value = event(1)
    await ingest.publish_page(value, job_key="test", expected_revision=0, cursor={"page": 1})
    script = tmp_path / "crash_after_commit.py"
    script.write_text('''
import asyncio, os, sys
from empire.core.config import load_config
from empire.bootstrap import build_manager

async def main():
    cfg = load_config(os.environ.get("EMPIRE_CONFIG"))
    cfg["redis"]["namespace"] = sys.argv[1]
    manager = build_manager(cfg)
    archive = manager.entries["pipeline.archive"].plugin
    async def crash(ids):
        os._exit(23)
    archive.acknowledge = crash
    await manager.start("pipeline.archive")
    await asyncio.sleep(20)

asyncio.run(main())
''', encoding="utf-8")
    result = await asyncio.to_thread(subprocess.run, [sys.executable, str(script), redis.prefix],
                                     capture_output=True, timeout=30)
    assert result.returncode == 23, result.stderr.decode(errors="replace")
    assert await redis.client.xlen(redis.stream) == 3
    assert await mysql.control(count, value[0].event_id) == 1
    assert await redis.client.xinfo_groups(redis.stream) == []
    await start()
    assert await redis.client.xlen(redis.stream) == 0
    assert await mysql.control(count, value[0].event_id) == 1
    assert (await ingest.checkpoint("test"))["revision"] == 1


async def test_queue_backpressure_does_not_advance_cursor(live):
    redis, _, _, ingest, event, start, _, _ = live
    ingest.settings["max_queue_entries"] = 3
    await ingest.publish_page(event(1), job_key="test", expected_revision=0, cursor={"page": 1})
    with pytest.raises(BackpressureError):
        await ingest.publish_page(event(2), job_key="test", expected_revision=1, cursor={"page": 2})
    assert (await ingest.checkpoint("test"))["cursor"] == {"page": 1}
    assert await redis.client.xlen(redis.stream) == 3
    await start()
    await ingest.publish_page(event(2), job_key="test", expected_revision=1, cursor={"page": 2})
    assert (await ingest.checkpoint("test"))["revision"] == 2


async def test_successful_response_extras_are_removed_before_redis(live):
    redis, _, _, ingest, event, _, _, _ = live
    values = event(1)
    original = values[1]
    payload = {**original.raw_payload, "response_debug": "must not persist"}
    payload["rows"] = [{**row, "trade": "100", "volume": "90000"} for row in payload["rows"]]
    values[1] = make_envelope(source=original.source, dataset=original.dataset,
                             business_key=original.business_key, job_key=original.job_key,
                             run_id=original.run_id, batch_id=original.batch_id, payload=payload)
    await ingest.publish_page(values, job_key="test", expected_revision=0, cursor={})
    messages = await redis.client.xrange(redis.stream)
    raw = messages[1][1]["envelope"]
    assert "trade" not in raw and "volume" not in raw and "response_debug" not in raw
    assert "unified_code" in raw and "source_symbol" in raw


async def test_sql_outage_records_archive_failure_without_error_response_eviction(live):
    redis, mysql, archive, ingest, event, start, _, registry = live
    await start()
    await ingest.publish_page(event(1), job_key="test", expected_revision=0, cursor={})
    original = mysql.archive

    async def fail(records):
        raise ConnectionError("Injected service outage")

    mysql.archive = fail
    with pytest.raises(ConnectionError):
        await archive.flush()
    assert await redis.client.xlen(redis.stream) == 3
    operational = registry.get("collection.records")
    assert not (await operational.list_error_summaries("test"))["total"]
    assert (await operational.list_archives("test"))[0]["status"] == "failed"
    mysql.archive = original
    await archive.flush()
    assert await redis.client.xlen(redis.stream) == 0
    assert (await operational.list_archives("test"))[0]["status"] == "complete"


async def test_unsupported_schema_keeps_original_pending_data(live):
    from empire.contracts.data import UnsupportedSchema
    redis, _, archive, _, event, start, _, _ = live
    await start()
    value = event(1)[1].model_copy(update={"schema_version": 2})
    await redis.client.xadd(redis.stream, {"envelope": value.model_dump_json()})
    with pytest.raises(UnsupportedSchema):
        await archive.flush()
    assert archive.blocked is True
    assert await redis.client.xlen(redis.stream) == 1
    errors = await archive.records.list_error_summaries("test")
    assert errors["rows"][0]["stage"] == "archive.schema"
    assert (await archive.records.list_archives("test"))[0]["status"] == "failed"


async def test_invalid_known_batch_removes_all_partial_messages(live):
    redis, _, archive, ingest, event, start, _, registry = live
    await start()
    values = event(1)
    await ingest.publish_page(values[:2], job_key="test", expected_revision=0, cursor={})
    invalid = values[1].model_copy(update={"content_hash": "0" * 64})
    await redis.client.xadd(redis.stream, {"envelope": invalid.model_dump_json()})
    await archive.flush()
    assert await redis.client.xlen(redis.stream) == 0
    assert (await registry.get("collection.records").list_error_summaries("test"))["total"] == 1


async def test_record_write_failure_does_not_drop_bad_response(live):
    redis, _, archive, _, _, start, _, registry = live
    await start()
    await redis.client.xadd(redis.stream, {"envelope": "invalid JSON"})
    operational = registry.get("collection.records")
    original = operational.add_error

    async def fail(*args, **kwargs):
        raise ConnectionError("Injected Redis record failure")

    operational.add_error = fail
    with pytest.raises(ConnectionError):
        await archive.flush()
    assert await redis.client.xlen(redis.stream) == 1
    operational.add_error = original
    await archive.flush()
    assert await redis.client.xlen(redis.stream) == 0


async def test_fresh_retry_releases_abandoned_partial_at_full_queue(live):
    redis, _, archive, ingest, event, start, _, _ = live
    await start()
    ingest.settings["max_queue_entries"] = 80
    sample = event(1)[0]
    old_id, new_id = uuid4().hex, uuid4().hex
    timestamp = datetime.now(UTC)

    def pages(batch_id, started_at):
        common = {"snapshot_id": batch_id, "started_at": started_at,
                  "expected_count": 40, "page_size": 1, "node": "hs_a"}
        values = []
        for page in range(1, 41):
            code = f"{41 - page:06d}"
            values.append(make_envelope(
                source=sample.source, dataset="stock.universe.page", business_key=f"{batch_id}:{page}",
                job_key="test", run_id=sample.run_id, batch_id=batch_id,
                payload={**common, "page": page,
                         "rows": [{"symbol": "sz" + code, "code": code, "name": "测试"}]},
            ))
        return common, values

    older, old_pages = pages(old_id, timestamp.isoformat())
    newer, new_pages = pages(new_id, (timestamp + timedelta(seconds=1)).isoformat())
    await ingest.publish_page(old_pages, job_key="test", expected_revision=0,
                              cursor={**older, "phase": "pages"})
    await ingest.publish_page(new_pages, job_key="test", expected_revision=1,
                              cursor={**newer, "phase": "verify"})
    assert await redis.client.xlen(redis.stream) == 80
    await archive.flush()
    assert await redis.client.xlen(redis.stream) == 40
    completion = make_envelope(
        source=sample.source, dataset="stock.universe.complete", business_key=f"{new_id}:complete",
        job_key="test", run_id=sample.run_id, batch_id=new_id,
        payload={**newer, "pages": 40, "collected": 40, "count_after": 40, "terminal_rows": []},
    )
    await ingest.publish_page([completion], job_key="test", expected_revision=2,
                              cursor={**newer, "phase": "complete"})
    await archive.flush()
    assert await redis.client.xlen(redis.stream) == 0
    archives = await archive.records.list_archives("test")
    assert archives[0]["status"] == "complete" and archives[0]["processed_count"] == 40
    assert archives[0]["written_count"] == 40
    assert archives[1]["status"] == "superseded"


async def test_fresh_checkpoint_never_discards_complete_batch_during_sql_outage(live):
    redis, mysql, archive, ingest, event, start, _, _ = live
    await start()
    values = event(1)
    await ingest.publish_page(values, job_key="test", expected_revision=0, cursor={
        "snapshot_id": uuid4().hex,
        "started_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat(), "phase": "pages",
    })
    original = mysql.archive

    async def fail(records):
        raise ConnectionError("Injected service outage")

    mysql.archive = fail
    with pytest.raises(ConnectionError):
        await archive.flush()
    assert await redis.client.xlen(redis.stream) == 3
    mysql.archive = original
    await archive.flush()
    assert await redis.client.xlen(redis.stream) == 0


async def test_completion_after_scan_cutoff_survives_fresh_checkpoint_and_sql_outage(live):
    redis, mysql, archive, ingest, event, start, count, _ = live
    await start()
    previous = event(1)
    await ingest.publish_page(previous[:2], job_key="test", expected_revision=0,
                              cursor={**previous[0].raw_payload, "phase": "pages"})
    original_scan, original_archive = archive._scan, mysql.archive
    newer = event(2)[0]
    newer = make_envelope(
        source=newer.source, dataset=newer.dataset, business_key=newer.business_key,
        job_key=newer.job_key, run_id=newer.run_id, batch_id=newer.batch_id,
        payload={**newer.raw_payload,
                 "started_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat()},
    )

    async def complete_then_restart_after_scan():
        groups = await original_scan()
        await ingest.publish_page(previous[2:], job_key="test", expected_revision=1,
                                  cursor={**previous[0].raw_payload, "phase": "complete"})
        await ingest.publish_page([newer], job_key="test", expected_revision=2,
                                  cursor={**newer.raw_payload, "phase": "pages"})
        return groups

    async def fail(records):
        raise ConnectionError("Injected MySQL outage while a complete older batch is pending")

    archive._scan, mysql.archive = complete_then_restart_after_scan, fail
    try:
        # This pass sees only the old partial group, but its completion is already
        # durable beyond the scan cutoff. A newer checkpoint cannot justify deletion.
        await archive.flush()
        assert await redis.client.xlen(redis.stream) == 4
        assert await archive.records.list_archives("test") == []
        archive._scan = original_scan
        with pytest.raises(ConnectionError):
            await archive.flush()
        assert await redis.client.xlen(redis.stream) == 4
        assert not (await archive.records.list_error_summaries("test"))["total"]
        mysql.archive = original_archive
        await archive.flush()
        assert await redis.client.xlen(redis.stream) == 1
        assert await mysql.control(count, previous[0].event_id) == 1
    finally:
        archive._scan, mysql.archive = original_scan, original_archive
