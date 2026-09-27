from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from empire.contracts.data import Envelope, UnsupportedSchema
from empire.contracts.plugin import PluginContext, PluginManifest
from empire.core.identity import safe_project_id
from empire.core.time import mysql_time
from empire.plugins.infra.collection_state import CollectionState
from empire.plugins.pipeline.archive_queue import (
    SCAN_WINDOW,
    TAIL_ID,
    ArchiveIndexFull,
    ArchiveLimits,
    ArchiveQueue,
    stream_number,
)
from empire.plugins.pipeline.fingerprints import FingerprintCache, digest


def now() -> str:
    return datetime.now(UTC).isoformat()


class ArchivePlugin:
    manifest = PluginManifest(
        "pipeline.archive", "业务归档",
        requires=("redis.store", "mysql.store", "dataset.catalog", "collection.records"),
        provides=("archive.worker",), description="完整业务数据提交 MySQL 后删除 Redis 临时数据",
    )

    def __init__(self, settings: dict) -> None:
        self.settings = settings
        self.limits = ArchiveLimits.from_settings(settings)
        self.queue = ArchiveQueue(self.limits.index_max_entries)
        self.redis = self.mysql = self.catalog = self.records = None
        self.task = None
        self.stop_event = asyncio.Event()
        self.wake_event = asyncio.Event()
        self.lock = asyncio.Lock()
        self.blocked = False
        self.isolated = {}
        self.isolation_retry = 0
        self.stats = {"status": "stopped", "archived": 0, "errors": 0}

    async def start(self, context: PluginContext) -> dict:
        self.redis = context.get("redis.store")
        self.mysql = context.get("mysql.store")
        self.catalog = context.get("dataset.catalog")
        self.records = context.get("collection.records")
        self.fingerprints = FingerprintCache(self.redis, self.settings, self.catalog.fingerprint_version)
        self.states = CollectionState(self.mysql, self.redis.prefix)
        self.stop_event = asyncio.Event()
        self.wake_event = asyncio.Event()
        self.blocked = False
        self.isolated.clear()
        self.isolation_retry = 0
        self.stats.update(status="ok", error="")
        self.queue = ArchiveQueue(self.limits.index_max_entries)

        async def run():
            failures = 0
            while not self.stop_event.is_set():
                # Scan/work budgets resume through the same queue cursor. A
                # publication during a turn wakes the next turn; queued work also
                # schedules continuation without waiting for the recovery scan.
                self.wake_event.clear()
                try:
                    await self.flush(retry_failed=False)
                    failures = 0
                    interval = self.settings.get("interval_seconds", 60)
                except Exception as exc:
                    failures += 1
                    interval = min(60, 5 * 2 ** min(failures - 1, 4))
                    self.stats.update(status="blocked" if self.blocked else "degraded", error=str(exc))
                    context.logger.warning("Archive deferred: %s", exc)
                if not self.blocked and not self.stats.get("scan_failed"):
                    interval = min(interval, self.queue.wait_seconds(self.blocked_projects))
                if self.wake_event.is_set() and not failures:
                    await asyncio.sleep(0)
                    continue
                stop = asyncio.create_task(self.stop_event.wait())
                wake = asyncio.create_task(self.wake_event.wait())
                try:
                    await asyncio.wait({stop, wake}, timeout=interval,
                                       return_when=asyncio.FIRST_COMPLETED)
                finally:
                    stop.cancel()
                    wake.cancel()
                    await asyncio.gather(stop, wake, return_exceptions=True)

        self.task = context.spawn(run(), name="archive-loop", critical=True)
        return {"archive.worker": self}

    def request_flush(self):
        """Wake the unified worker after durable queue publication."""
        self.wake_event.set()

    async def acknowledge(self, ids: list[str]) -> None:
        # Valid messages reach here after commit, confirmed equality or stale-version
        # rejection. A fingerprint hit is proof from a prior successful transaction.
        for offset in range(0, len(ids), 500):
            await self.redis.client.xdel(self.redis.stream, *ids[offset:offset + 500])
            self.queue.forget(ids[offset:offset + 500])

    async def _record_invalid(self, ident, raw, envelope, exc, *, schema=False):
        owner = self.catalog.schema_owner(envelope) if schema and envelope else None
        project = safe_project_id(envelope.job_key if envelope else "unknown")
        if owner is not None:
            project = owner
        elif envelope:
            try:
                project = self.catalog.project_id(envelope)
            except UnsupportedSchema:
                pass
        await self.records.add_error(project, stage="archive.schema" if schema else "archive.validate",
            error=str(exc), raw_body=raw,
            metadata={"stream_id": ident, "stream": self.redis.stream},
            record_id=hashlib.sha256(f"{self.redis.stream}:{ident}".encode()).hexdigest())
        if schema:
            if owner is None:
                self.blocked = True
            else:
                if ident not in self.isolated and ident not in self.queue.ids and self.indexed_count >= self.queue.limit:
                    raise ArchiveIndexFull("归档隔离与消息索引达到容量上限；消息保留")
                self.isolated[ident] = owner
            if envelope:
                await self._history(project, envelope.batch_id, "failed", now(), error=str(exc), stable=True)
        else:
            self.stats["errors"] += 1

    @property
    def indexed_count(self):
        return len(self.queue.ids) + sum(ident not in self.queue.ids for ident in self.isolated)

    @property
    def blocked_projects(self):
        return set(self.isolated.values())

    async def _recheck_isolated(self, force):
        if not self.isolated or (not force and monotonic() < self.isolation_retry):
            return
        self.isolation_retry = monotonic() + 60
        began, size = monotonic(), 0
        # Rotate a bounded ID-only index so a large quarantine cannot starve recovery.
        for ident in list(self.isolated)[:self.limits.scan_max_messages]:
            if size >= self.limits.scan_max_bytes or (monotonic() - began) * 1000 >= self.limits.scan_time_ms:
                break
            project = self.isolated.pop(ident)
            self.isolated[ident] = project
            rows = await self.redis.client.xrange(self.redis.stream, min=ident, max=ident, count=1)
            if not rows:
                self.isolated.pop(ident)
                continue
            size += len(rows[0][1].get("envelope", "").encode())
            envelope = Envelope.model_validate_json(rows[0][1].get("envelope", ""))
            try:
                incremental = self.catalog.incremental(envelope)
            except UnsupportedSchema:
                continue
            self.queue.add(ident, envelope, incremental, self.catalog.project_id(envelope),
                           self.catalog.is_complete(envelope))
            self.isolated.pop(ident)

    async def _scan(self):
        """Advance a bounded window; retain IDs only, not queue-wide payloads."""
        self.blocked = False
        queue, limits = self.queue, self.limits
        scanned = size = 0
        began = monotonic()
        if queue.cutoff is None:
            tail = await self.redis.client.eval(TAIL_ID, 1, self.redis.stream)
            if not tail:
                self.queue = ArchiveQueue(limits.index_max_entries)
                self.stats.update(scan_messages=0, scan_bytes=0, scan_more=False)
                self.blocked = False
                self.isolated.clear()
                return
            if stream_number(tail) < stream_number(queue.cursor):
                self.queue = queue = ArchiveQueue(limits.index_max_entries)
            queue.cutoff = tail
        queue.more_scan = True
        while not self.stop_event.is_set() and scanned < limits.scan_max_messages:
            if scanned and (size >= limits.scan_max_bytes or
                            (monotonic() - began) * 1000 >= limits.scan_time_ms):
                break
            rows, byte_count, oversized, required = await self.redis.client.eval(
                SCAN_WINDOW, 1, self.redis.stream, "(" + queue.cursor, queue.cutoff,
                min(limits.batch_size, limits.scan_max_messages - scanned), limits.scan_max_bytes - size)
            if not rows:
                if oversized:
                    if required > limits.scan_max_bytes:
                        raise ValueError("待归档单消息超过 scan_max_bytes；消息保留，须调整扫描预算")
                    break
                queue.finish_scan()
                break
            size += byte_count
            for ident, pairs in rows:
                raw = dict(zip(pairs[::2], pairs[1::2])).get("envelope", "")
                envelope = None
                try:
                    envelope = Envelope.model_validate_json(raw)
                    incremental = self.catalog.incremental(envelope)
                except UnsupportedSchema as exc:
                    await self._record_invalid(ident, raw, envelope, exc, schema=True)
                    if self.blocked:
                        raise
                except (ValueError, TypeError) as exc:
                    # A future or damaged envelope may fail current validation before
                    # the catalog can resolve it. Never delete it as ordinary bad data.
                    try:
                        header = json.loads(raw)
                    except (ValueError, TypeError):
                        header = None
                    if isinstance(header, dict) and header.get("schema_version", 1) != 1:
                        error = UnsupportedSchema("未知版本消息无法可靠识别归属；消息保留，归档全局暂停")
                        await self._record_invalid(ident, raw, None, error, schema=True)
                        raise error from None
                    await self._record_invalid(ident, raw, envelope, exc)
                    await self.acknowledge([ident])
                else:
                    if ident not in queue.ids and ident not in self.isolated and self.indexed_count >= queue.limit:
                        raise ArchiveIndexFull("归档隔离与消息索引达到容量上限；消息保留")
                    queue.add(ident, envelope, incremental, self.catalog.project_id(envelope),
                              self.catalog.is_complete(envelope))
                queue.cursor = ident
                scanned += 1
            if stream_number(queue.cursor) >= stream_number(queue.cutoff):
                queue.finish_scan()
                break
            await asyncio.sleep(0)
        if queue.cutoff is None:
            # A publication wake may have been consumed by an earlier quantum of
            # this SAME cutoff. Recheck its successor before going idle, otherwise
            # new tail messages could sleep until the 60-second recovery scan.
            tail = await self.redis.client.eval(TAIL_ID, 1, self.redis.stream)
            queue.more_scan = bool(tail and stream_number(tail) > stream_number(queue.cursor))
        self.blocked = False
        self.stats.update(scan_messages=scanned, scan_bytes=size, scan_more=queue.more_scan,
                          scan_elapsed_ms=round((monotonic() - began) * 1000, 2))

    async def _load_records(self, ids):
        records = []
        # Full stock metadata is one business unit. Raw bodies live only for this
        # read; unfinished batches otherwise retain just bounded Stream IDs.
        for ident in ids:
            if self.stop_event.is_set():
                return None
            page = await self.redis.client.xrange(self.redis.stream, min=ident, max=ident, count=1)
            if not page:
                self.queue.forget([ident])  # ACK may have succeeded before a cancelled Redis reply.
                continue
            raw = page[0][1].get("envelope", "")
            envelope = Envelope.model_validate_json(raw)
            record = {"id": ident, "envelope": envelope.model_copy(update={"raw_payload": {}})}
            try:
                normalized = self.catalog.normalize(envelope)
                record["normalized"] = {key: value for key, value in normalized.items() if key != "rows"}
            except UnsupportedSchema as exc:
                await self._record_invalid(ident, raw, envelope, exc, schema=True)
                raise
            except (ValueError, TypeError) as exc:
                await self._record_invalid(ident, raw, envelope, exc)
                record["invalid"] = str(exc)
            records.append(record)
        return records

    async def _load_rows(self, records: list[dict]) -> list[dict]:
        """Only one validated batch (at most 100,000 rows) enters working memory."""
        selected = {}
        result = []
        for record in records:
            page = record["normalized"].get("page")
            if page is not None:
                selected.setdefault(page, record["id"])
            elif self.catalog.is_complete(record["envelope"]) and not result:
                result.append(record)
        ids = list(selected.values())
        for offset in range(0, len(ids), 20):
            if self.stop_event.is_set():
                return None
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
        try:
            cursor = json.loads(state) if state else {}
            if not isinstance(cursor, dict) or not cursor.get("snapshot_id") or not cursor.get("started_at"):
                return False
            timestamp = datetime.fromisoformat(cursor["started_at"])
            if timestamp.tzinfo is None:
                return False
            started = mysql_time(timestamp)
            namespace = self.catalog.namespace(first["envelope"])
            self.catalog.fingerprint_version(namespace).key([
                started.isoformat(timespec="microseconds"), cursor["snapshot_id"]])
        except (ValueError, TypeError, OverflowError):
            # A broken/newer-looking checkpoint is not permission to discard pages.
            return False
        previous = first["normalized"]
        newer = (cursor["snapshot_id"] != previous["snapshot_id"]
                 and (started, cursor["snapshot_id"]) > (previous["started_at"], previous["snapshot_id"]))
        if not newer:
            return False
        # The scan has a fixed upper bound. Completion may have arrived after that
        # bound but before the new checkpoint. Check the durable tail before removing
        # any old pages. Once this newer checkpoint exists, CAS prevents the old
        # producer from adding further messages, so this tail view is sufficient.
        tail = await self.redis.client.eval(TAIL_ID, 1, self.redis.stream)
        if not tail:
            return True
        # No second unbounded tail scan. Capture the tail AFTER the new checkpoint
        # and wait for the shared scanner to cross that fence before deleting.
        if stream_number(tail) > stream_number(self.queue.stable_cutoff):
            batch = self.queue.ids.get(records[0]["id"])
            if batch:
                batch.checked = False
                batch.dirty = True
                self.queue.dirty.add(batch)
            self.queue.more_scan = True
            return False
        return True

    async def _history(self, project: str, batch: str, status: str, started: str,
                       *, processed_count: int | None = None, written_count: int | None = None,
                       error: str = "", stable: bool = False) -> None:
        record = {
            "id": f"{batch}:{status}" if stable else uuid4().hex,
            "snapshot_id": batch, "status": status, "started_at": started,
            "finished_at": now(), "error": error,
        }
        if processed_count is not None:
            record["processed_count"] = processed_count
        if written_count is not None:
            record["written_count"] = written_count
        await self.records.add_archive(project, record)

    async def _aggregate_result(self, envelope, batch: str, status: str,
                      *, count: int = 0, error: str = "", started_at=None) -> None:
        value = json.dumps({
            "snapshot_id": batch, "status": status, "row_count": count,
            "expected_count": count, "error_text": error, "finished_at": now(),
            "started_at": started_at.isoformat() if started_at else None,
        }, ensure_ascii=False)
        keys = self.catalog.aggregate_result_keys(envelope, self.redis.prefix)
        if status == "complete" and started_at:
            await self.redis.client.set(keys["committed"], value)
        await self.redis.client.set(keys["result"], value)

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
            outcome = await self._archive_data(full, normalized)
            await self._history(project, envelope.event_id, "complete", started,
                                processed_count=outcome["row_count"],
                                written_count=outcome.get("written_count"), stable=True)
            await self._incremental_result(envelope, normalized["page"], "complete", outcome["row_count"])
            await self.acknowledge([record["id"]])
            self.stats["archived"] += 1
            self.stats.update(last_success=now())

    async def _archive_data(self, envelope, data):
        namespace, plan = self.catalog.fingerprint_plan(envelope, data)
        version_contract = self.catalog.fingerprint_version(namespace)
        cached = await self.fingerprints.get(namespace, envelope.source, list(plan))
        pending, confirmed = set(), {}
        stale = 0
        for ident, (content, version) in plan.items():
            value = {"hash": digest(content), "version": version}
            old = cached.get(ident)
            if old and version_contract.compare(version, old["version"]) < 0:
                stale += 1
            elif old and value["hash"] == old["hash"]:
                confirmed[ident] = value
            else:
                pending.add(ident)
        count = data.get("row_count", data.get("expected_count", 0))
        outcome = {"status": self.catalog.stale_outcome(envelope) if stale else "complete",
                   "row_count": count, "written_count": 0}
        if pending or not plan:
            subset = self.catalog.fingerprint_subset(envelope, data, pending)
            outcome = (await self.mysql.archive([{
                "envelope": envelope, "normalized": subset, "writer": self.states.writer(self.catalog, data),
            }]))[0]
            # Rejected old SQL versions must never be cached as the current content.
            accepted = outcome["confirmed"]
            for ident in accepted:
                content, version = plan[ident]
                confirmed[ident] = {"hash": digest(content), "version": version}
            outcome["row_count"] = count
        # Commit/equality precedes cache; cache precedes queue ACK. Any failure keeps
        # the queue replayable. Never cache uncommitted collection output.
        await self.fingerprints.put(namespace, envelope.source, confirmed)
        return outcome

    async def _flush_aggregate(self, records, project, current):
        first = records[0]
        source, batch = first["envelope"].source, first["envelope"].batch_id
        ids = [record["id"] for record in records]
        started = now()
        invalid = next((record["invalid"] for record in records if "invalid" in record), None)
        keys = self.catalog.aggregate_result_keys(first["envelope"], self.redis.prefix)
        saved = await self.redis.client.get(keys["result"])
        saved_result = json.loads(saved) if saved else {}
        if (saved_result.get("snapshot_id") == batch
                and saved_result.get("status") == "invalid"):
            invalid = invalid or saved_result.get("error_text") or "已核验为无效批次"
        if invalid:
            await self._aggregate_result(first["envelope"], batch, "invalid", error=invalid)
            await self._history(project, batch, "invalid", started, error=invalid, stable=True)
            await self.acknowledge(ids)
            return
        if (not any(self.catalog.is_complete(record["envelope"]) for record in records)
                and await self._abandoned_partial(records)):
            await self._history(project, batch, "superseded", started,
                                error="重新采集已替代此前未完成的临时进度", stable=True)
            await self.acknowledge(ids)
            return
        # Only the validated, expiring fingerprint or SQL state can
        # prove a replay. stocks:committed is UI progress, not evidence.
        namespace = self.catalog.namespace(first["envelope"])
        proof = await self.fingerprints.get(namespace, source, ["current"])
        previous = proof["current"]["version"] if proof else None
        complete = any(self.catalog.is_complete(record["envelope"]) for record in records)
        has_pages = any("page" in record["normalized"] for record in records)
        if previous is None and (not complete or not has_pages):
            if source not in current:
                state = await self.mysql.control(self.states.read, source, project)
                current[source] = state.get("version")
            previous = current[source]
        incoming = [first["normalized"]["started_at"].isoformat(timespec="microseconds"), batch]
        if previous and self.catalog.fingerprint_version(namespace).compare(incoming, previous) <= 0:
            # Existing committed rows prove a replay or superseded incomplete run.
            await self._history(project, batch, "replayed" if batch == previous[1]
                                else "superseded", started, stable=True)
            await self.acknowledge(ids)
            return
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
            await self._aggregate_result(first["envelope"], batch, "invalid", error=str(exc))
            await self._history(project, batch, "invalid", started, error=str(exc), stable=True)
            await self.acknowledge(ids)
            self.stats["errors"] += 1
            return
        if data is None:
            return
        loaded = await self._load_rows(records)
        if loaded is None:
            return
        data = self.catalog.assemble(loaded)
        outcome = await self._archive_data(first["envelope"], data)
        # Every await after commit may fail: the unchanged stream is safely replayable.
        if outcome["status"] != "superseded":
            await self._aggregate_result(first["envelope"], batch, "complete",
                                         count=data["expected_count"], started_at=data["started_at"])
        await self._history(project, batch, outcome["status"], started,
                            processed_count=outcome["row_count"],
                            written_count=outcome.get("written_count"), stable=True)
        await self.acknowledge(ids)
        self.stats["archived"] += len(ids)
        self.stats.update(last_success=now())

    async def flush(self, *, retry_failed=True) -> None:
        """One bounded scheduling quantum; remaining work wakes the resident loop."""
        async with self.lock:
            self.stats["scan_failed"] = False
            await self._recheck_isolated(retry_failed)
            index_error = None
            try:
                await self._scan()
            except ArchiveIndexFull as exc:
                # Drain already discovered independent pages to free index slots.
                # Never pretend a truncated stock scan is a completed batch fence.
                index_error = exc.with_traceback(None)
            except Exception:
                self.stats["scan_failed"] = True
                raise
            self.queue.recheck(retry_failed=retry_failed)
            failures, current = [], {}
            units, began = 0, monotonic()
            while not self.stop_event.is_set() and units < self.limits.work_max_units:
                if units and (monotonic() - began) * 1000 >= self.limits.work_time_ms:
                    break
                batch = self.queue.take(self.blocked_projects)
                if batch is None:
                    break
                units += 1
                ids = [next(iter(batch.ids))] if batch.incremental and batch.ids else list(batch.ids)
                records = None
                failed = False
                try:
                    records = await self._load_records(ids)
                    batch.checked = True
                    if records:
                        if batch.incremental:
                            await self._flush_incremental(records, batch.project)
                        else:
                            await self._flush_aggregate(records, batch.project, current)
                    self.stats["last_project"] = batch.project
                except Exception as exc:
                    failed = True
                    if not failures:
                        failures.append(exc.with_traceback(None))
                    try:
                        await self._history(batch.project, batch.key[2], "failed", now(), error=str(exc))
                    except Exception:
                        pass
                    if self.blocked:
                        raise
                except BaseException:
                    self.queue.schedule(batch)
                    raise
                finally:
                    records = None
                    self.queue.reschedule(batch, failed=failed)
            if index_error and self.indexed_count >= self.queue.limit:
                self.stats["scan_failed"] = True
                failures.append(index_error)
            self.stats.update(pending=await self.redis.client.xlen(self.redis.stream),
                staging_batches=sum(not b.incremental and not b.complete for b in self.queue.batches.values()),
                indexed_messages=len(self.queue.ids), indexed_batches=len(self.queue.batches),
                ready_projects=sum(p not in self.queue.delayed for p in self.queue.ready),
                retry_projects=len(self.queue.delayed),
                work_units=units, work_elapsed_ms=round((monotonic() - began) * 1000, 2))
            if self.queue.more_scan or any(p not in self.blocked_projects and p not in self.queue.delayed
                                          for p in self.queue.ready):
                self.wake_event.set()
            if failures:
                self.stats.update(status="degraded", error=str(failures[0]))
                raise failures[0]
            if self.isolated:
                self.stats.update(status="degraded", error="部分项目数据契约不兼容，消息保留等待恢复")
            elif not self.queue.delayed:
                self.stats.update(status="ok", error="")

    async def stop(self) -> None:
        self.stop_event.set()
        self.wake_event.set()
        if self.task:
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        async with self.lock:
            pass
        self.queue = ArchiveQueue(self.limits.index_max_entries)
        self.stats.update(status="stopped", scan_more=False, indexed_messages=0,
                          indexed_batches=0, ready_projects=0, retry_projects=0)
        self.isolated.clear()

    def health(self) -> dict:
        return {**self.stats, "blocked_projects": sorted(self.blocked_projects),
                "isolated_messages": len(self.isolated)}
