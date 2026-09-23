from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from redis.exceptions import ResponseError

from empire.contracts.data import Envelope, UnsupportedSchema
from empire.contracts.plugin import PluginContext, PluginManifest
from empire.plugins.collection.records import project_id_for

ACK_DELETE_LUA = """
for i = 2, #ARGV do
    redis.call('XACK', KEYS[1], ARGV[1], ARGV[i])
    redis.call('XDEL', KEYS[1], ARGV[i])
end
return #ARGV - 1
"""


def now() -> str:
    return datetime.now(UTC).isoformat()


class ArchivePlugin:
    manifest = PluginManifest(
        "pipeline.archive", "每分钟归档",
        requires=("redis.store", "mysql.store", "dataset.catalog", "collection.records"),
        provides=("archive.worker",), description="完整业务数据提交 MySQL 后删除 Redis 临时数据",
    )

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.redis = self.mysql = self.catalog = self.records = None
        self.task = None
        self.stop_event = asyncio.Event()
        self.lock = asyncio.Lock()
        self.blocked = False
        self.stats = {"status": "stopped", "archived": 0, "errors": 0}

    async def start(self, context: PluginContext) -> dict:
        self.redis = context.get("redis.store")
        self.mysql = context.get("mysql.store")
        self.catalog = context.get("dataset.catalog")
        self.records = context.get("collection.records")
        try:
            await self.redis.client.xgroup_create(self.redis.stream, self.redis.group, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise
        self.stop_event = asyncio.Event()
        self.blocked = False
        self.stats.update(status="ok", error="")

        async def run():
            failures = 0
            while not self.stop_event.is_set():
                try:
                    await self.flush()
                    failures = 0
                    interval = self.settings.get("interval_seconds", 60)
                except Exception as exc:
                    failures += 1
                    interval = min(60, 5 * 2 ** min(failures - 1, 4))
                    self.stats.update(status="blocked" if self.blocked else "degraded", error=str(exc))
                    context.logger.warning("Archive deferred: %s", exc)
                try:
                    await asyncio.wait_for(self.stop_event.wait(), timeout=interval)
                except TimeoutError:
                    pass

        self.task = context.spawn(run(), name="archive-loop")
        return {"archive.worker": self}

    async def acknowledge(self, ids: list[str]) -> None:
        # An incomplete list has no SQL staging table: it stays in this durable stream.
        # Valid business messages reach here only after their SQL transaction committed.
        for offset in range(0, len(ids), 500):
            await self.redis.client.eval(
                ACK_DELETE_LUA, 1, self.redis.stream, self.redis.group, *ids[offset:offset + 500]
            )

    async def _scan(self) -> dict:
        groups = defaultdict(list)
        last = await self.redis.client.xrevrange(self.redis.stream, count=1)
        if not last:
            return groups
        cutoff, cursor = last[0][0], "-"
        count = min(100, max(1, int(self.settings.get("batch_size", 100))))
        while not self.stop_event.is_set():
            messages = await self.redis.client.xrange(self.redis.stream, min=cursor, max=cutoff, count=count)
            if not messages:
                break
            for stream_id, fields in messages:
                raw = fields.get("envelope", "")
                envelope = None
                try:
                    envelope = Envelope.model_validate_json(raw)
                    normalized = self.catalog.normalize(envelope)
                except UnsupportedSchema as exc:
                    self.blocked = True
                    project = project_id_for(envelope.source, envelope.job_key)
                    await self.records.add_error(
                        project, stage="archive.schema", error=str(exc), raw_body=raw,
                        metadata={"stream_id": stream_id, "stream": self.redis.stream},
                        record_id=hashlib.sha256(f"{self.redis.stream}:{stream_id}".encode()).hexdigest(),
                    )
                    await self._history(project, envelope.batch_id, "failed", now(),
                                        error=str(exc), stable=True)
                    raise
                except (ValueError, TypeError) as exc:
                    project = project_id_for(envelope.source, envelope.job_key) if envelope else "unknown"
                    await self.records.add_error(
                        project, stage="archive.validate", error=str(exc), raw_body=raw,
                        metadata={"stream_id": stream_id, "stream": self.redis.stream},
                        record_id=hashlib.sha256(f"{self.redis.stream}:{stream_id}".encode()).hexdigest(),
                    )
                    # A known invalid batch is removed as a unit after its error is durable.
                    if envelope:
                        groups[(envelope.source, envelope.batch_id)].append({
                            "id": stream_id, "envelope": envelope.model_copy(update={"raw_payload": {}}),
                            "invalid": str(exc),
                        })
                    else:
                        await self.acknowledge([stream_id])
                    self.stats["errors"] += 1
                    continue
                # Drop the successful response/envelope payload copy from working memory.
                groups[(envelope.source, envelope.batch_id)].append({
                    "id": stream_id, "envelope": envelope.model_copy(update={"raw_payload": {}}),
                    "normalized": {key: value for key, value in normalized.items() if key != "rows"},
                })
            cursor = "(" + messages[-1][0]
            await asyncio.sleep(0)
        return groups

    async def _load_rows(self, records: list[dict]) -> list[dict]:
        """Only one validated batch (at most 100,000 rows) enters working memory."""
        selected = {}
        result = []
        for record in records:
            page = record["normalized"].get("page")
            if page is not None:
                selected.setdefault(page, record["id"])
            elif record["envelope"].dataset.endswith(".complete") and not result:
                result.append(record)
        ids = list(selected.values())
        for offset in range(0, len(ids), 20):
            async with self.redis.client.pipeline(transaction=False) as pipe:
                for ident in ids[offset:offset + 20]:
                    pipe.xrange(self.redis.stream, min=ident, max=ident, count=1)
                pages = await pipe.execute()
            for page in pages:
                if not page:
                    raise RuntimeError("待归档分页在读取期间消失，保留其余数据等待检查")
                ident, fields = page[0]
                envelope = Envelope.model_validate_json(fields["envelope"])
                result.append({"id": ident, "envelope": envelope.model_copy(update={"raw_payload": {}}),
                               "normalized": self.catalog.normalize(envelope)})
        return result

    async def _abandoned_partial(self, records: list[dict]) -> bool:
        first = records[0]
        state = await self.redis.client.hget(
            f"{self.redis.prefix}:checkpoint:{first['envelope'].job_key}", "cursor"
        )
        cursor = json.loads(state) if state else {}
        if not cursor.get("snapshot_id") or not cursor.get("started_at"):
            return False
        started = datetime.fromisoformat(cursor["started_at"]).astimezone(UTC).replace(tzinfo=None)
        previous = first["normalized"]
        newer = (cursor["snapshot_id"] != previous["snapshot_id"]
                 and (started, cursor["snapshot_id"]) > (previous["started_at"], previous["snapshot_id"]))
        if not newer:
            return False
        # The scan has a fixed upper bound. Completion may have arrived after that
        # bound but before the new checkpoint. Check the durable tail before removing
        # any old pages. Once this newer checkpoint exists, CAS prevents the old
        # producer from adding further messages, so this tail view is sufficient.
        last = await self.redis.client.xrevrange(self.redis.stream, count=1)
        if not last:
            return True
        cutoff, after = last[0][0], "(" + records[-1]["id"]
        while True:
            messages = await self.redis.client.xrange(self.redis.stream, min=after, max=cutoff, count=100)
            if not messages:
                return True
            for _, fields in messages:
                try:
                    value = json.loads(fields.get("envelope", ""))
                except (TypeError, ValueError):
                    continue
                if (isinstance(value, dict) and value.get("source") == first["envelope"].source
                        and value.get("batch_id") == previous["snapshot_id"]
                        and value.get("dataset") == "stock.universe.complete"):
                    return False
            after = "(" + messages[-1][0]

    async def _history(self, project: str, batch: str, status: str, started: str,
                       *, count: int = 0, error: str = "", stable: bool = False) -> None:
        await self.records.add_archive(project, {
            "id": f"{batch}:{status}" if stable else uuid4().hex,
            "snapshot_id": batch, "status": status, "started_at": started,
            "finished_at": now(), "row_count": count, "error": error,
        })

    async def _result(self, source: str, batch: str, status: str,
                      *, count: int = 0, error: str = "", started_at=None) -> None:
        value = json.dumps({
            "snapshot_id": batch, "status": status, "row_count": count,
            "expected_count": count, "error_text": error, "finished_at": now(),
            "started_at": started_at.isoformat() if started_at else None,
        }, ensure_ascii=False)
        if status == "complete" and started_at:
            await self.redis.client.set(f"{self.redis.prefix}:stocks:committed:{source}", value)
        await self.redis.client.set(f"{self.redis.prefix}:stocks:result:{source}", value)

    async def _incremental_result(self, envelope, page, status, count=0, error=""):
        value = json.dumps({"batch_id": envelope.batch_id, "page": page, "status": status,
                            "row_count": count, "error_text": error,
                            "observed_at": envelope.observed_at.isoformat(timespec="microseconds")}, ensure_ascii=False)
        await self.redis.client.eval("""
            local raw = redis.call('GET', KEYS[1])
            local new = cjson.decode(ARGV[1])
            if raw then
                local old = cjson.decode(raw)
                if old.batch_id == new.batch_id then
                    if old.status == 'invalid' then return 0 end
                    if new.status ~= 'invalid' and old.page > new.page then return 0 end
                elseif old.observed_at > new.observed_at then return 0 end
            end
            redis.call('SET', KEYS[1], ARGV[1])
            return 1
        """, 1, f"{self.redis.prefix}:archive:progress:{envelope.job_key}", value)

    async def _flush_incremental(self, records, project):
        """Independent business pages archive in order without SQL staging tables."""
        for record in records:
            if self.stop_event.is_set():
                return
            envelope = record["envelope"]
            started = now()
            if record.get("invalid"):
                await self._incremental_result(envelope, 0, "invalid", error=record["invalid"])
                await self._history(project, envelope.event_id, "invalid", started,
                                    error=record["invalid"], stable=True)
                await self.acknowledge([record["id"]])
                continue
            page = await self.redis.client.xrange(self.redis.stream, min=record["id"], max=record["id"], count=1)
            if not page:
                raise RuntimeError("待归档业务分页在读取期间消失")
            full = Envelope.model_validate_json(page[0][1]["envelope"])
            normalized = self.catalog.normalize(full)
            partition = self.catalog.observation_partition(full, normalized)
            version_key = f"{self.redis.prefix}:archive:observed:{full.dataset}:{full.source}"
            observed = full.observed_at.isoformat(timespec="microseconds")
            previous = await self.redis.client.hget(version_key, partition) if partition else None
            if previous and previous >= observed:
                outcome = {"row_count": normalized["row_count"], "written_count": 0}
            else:
                outcome = (await self.mysql.archive([{"envelope": full, "normalized": normalized,
                                                      "writer": self.catalog.write}]))[0]
                if partition:
                    await self.redis.client.hset(version_key, partition, observed)
            await self._history(project, envelope.event_id, "complete", started,
                                count=outcome["row_count"], stable=True)
            await self._incremental_result(envelope, normalized["page"], "complete", outcome["row_count"])
            await self.acknowledge([record["id"]])
            self.stats["archived"] += 1
            self.stats.update(last_success=now())

    async def flush(self) -> None:
        async with self.lock:
            groups = await self._scan()
            self.blocked = False
            failures = []
            current = {}
            waiting = 0
            for (source, batch), records in groups.items():
                if self.stop_event.is_set():
                    break
                first = records[0]
                project = project_id_for(source, first["envelope"].job_key)
                ids = [record["id"] for record in records]
                started = now()
                try:
                    if self.catalog.incremental(first["envelope"]):
                        await self._flush_incremental(records, project)
                        continue
                    invalid = next((record["invalid"] for record in records if "invalid" in record), None)
                    saved = await self.redis.client.get(f"{self.redis.prefix}:stocks:result:{source}")
                    saved_result = json.loads(saved) if saved else {}
                    if (saved_result.get("snapshot_id") == batch
                            and saved_result.get("status") == "invalid"):
                        invalid = invalid or saved_result.get("error_text") or "已核验为无效批次"
                    if invalid:
                        await self._result(source, batch, "invalid", error=invalid)
                        await self._history(project, batch, "invalid", started, error=invalid, stable=True)
                        await self.acknowledge(ids)
                        continue
                    if (not any(record["envelope"].dataset.endswith(".complete") for record in records)
                            and await self._abandoned_partial(records)):
                        await self._history(project, batch, "superseded", started,
                                            error="重新采集已替代此前未完成的临时进度", stable=True)
                        await self.acknowledge(ids)
                        continue
                    if source not in current:
                        current[source] = await self.mysql.read(self.catalog.current, self.mysql.engine, source)
                    previous = current[source]
                    confirmed = await self.redis.client.get(f"{self.redis.prefix}:stocks:committed:{source}")
                    if confirmed:
                        committed = json.loads(confirmed)
                        marker = {"started_at": datetime.fromisoformat(committed["started_at"]),
                                  "generation": committed["snapshot_id"]}
                        if not previous or (marker["started_at"], marker["generation"]) > (previous["started_at"], previous["generation"]):
                            previous = marker
                    incoming = (first["normalized"]["started_at"], batch)
                    if previous and incoming <= (previous["started_at"], previous["generation"]):
                        # Existing committed rows prove a replay or superseded incomplete run.
                        await self._history(project, batch, "replayed" if batch == previous["generation"]
                                            else "superseded", started, stable=True)
                        await self.acknowledge(ids)
                        continue
                    try:
                        data = self.catalog.assemble(records, include_rows=False)
                    except ValueError as exc:
                        await self.records.add_error(
                            project, stage="archive.assemble", error=str(exc),
                            raw_body=json.dumps([record["normalized"] for record in records],
                                                ensure_ascii=False, default=str),
                            metadata={"snapshot_id": batch, "stream_ids": ids},
                            record_id=f"batch-{batch}",
                        )
                        await self._result(source, batch, "invalid", error=str(exc))
                        await self._history(project, batch, "invalid", started, error=str(exc), stable=True)
                        await self.acknowledge(ids)
                        self.stats["errors"] += 1
                        continue
                    if data is None:
                        waiting += 1
                        continue
                    loaded = await self._load_rows(records)
                    data = self.catalog.assemble(loaded)
                    outcome = (await self.mysql.archive([{
                        "envelope": first["envelope"], "normalized": data, "writer": self.catalog.write,
                    }]))[0]
                    # Every await after commit may fail: the unchanged stream is safely replayable.
                    if outcome["status"] != "superseded":
                        await self._result(source, batch, "complete", count=data["expected_count"],
                                           started_at=data["started_at"])
                    await self._history(project, batch, outcome["status"], started,
                                        count=outcome["row_count"], stable=True)
                    await self.acknowledge(ids)
                    current[source] = await self.mysql.read(self.catalog.current, self.mysql.engine, source)
                    self.stats["archived"] += len(ids)
                    self.stats.update(last_success=now())
                except Exception as exc:
                    # SQL outages and post-commit Redis failures never evict pending good data.
                    if not failures:
                        failures.append(exc.with_traceback(None))
                    try:
                        await self._history(project, batch, "failed", started, error=str(exc))
                    except Exception:
                        pass
                finally:
                    # Do not retain one batch's business rows while loading the next batch.
                    data = loaded = None
            self.stats.update(pending=await self.redis.client.xlen(self.redis.stream), staging_batches=waiting)
            if failures:
                self.stats.update(status="degraded", error=str(failures[0]))
                raise failures[0]
            self.stats.update(status="ok", error="")

    async def stop(self) -> None:
        self.stop_event.set()
        if self.task:
            await self.task
            self.task = None
        async with self.lock:
            pass
        self.stats["status"] = "stopped"

    def health(self) -> dict:
        return dict(self.stats)
