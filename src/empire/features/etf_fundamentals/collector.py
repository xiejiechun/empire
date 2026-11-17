"""Frozen bounded plans, atomic publication, then whole-round archive confirmation."""

import asyncio
import base64
import json
import zlib
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.features.etf_fundamentals.contract import (
    CONTRACT,
    MAX_BYTES,
    NAV_DATASET,
    SHARE_DATASET,
    SOURCES,
    digest,
    years,
)
from empire.features.etf_fundamentals.download import Downloads
from empire.features.etf_fundamentals.source import NAV_URL, PAGES, SSE_URL, SZSE_URL
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
)


def pack_cursor(cursor):
    if not cursor:
        return {}
    units = cursor["units"]
    fields = sorted(units[0]) if units else []
    if any(sorted(u) != fields for u in units):
        raise ValueError("ETF冻结单元字段不一致")
    encoded = json.dumps([fields, [[u[k] for k in fields] for u in units]], separators=(",", ":")).encode()
    if len(encoded) > 1024 * 1024:
        raise ValueError("ETF冻结计划超过1MiB")
    result = {**cursor, "units": base64.b85encode(zlib.compress(encoded, 9)).decode("ascii")}
    if len(json.dumps(result, separators=(",", ":")).encode()) > 16384:
        raise ValueError("ETF冻结断点超过公共16KiB上限")
    return result


def unpack_cursor(cursor):
    if not cursor:
        return {}
    data = base64.b85decode(cursor["units"])
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(data, 1024 * 1024 + 1)
    except zlib.error as exc:
        raise ValueError("ETF冻结计划损坏") from exc
    if len(raw) > 1024 * 1024 or not decoder.eof or decoder.unused_data:
        raise ValueError("ETF冻结计划损坏或超限")
    fields, rows = json.loads(raw)
    if not isinstance(rows, list) or not 0 <= len(rows) <= 10000:
        raise ValueError("ETF冻结单元集合无效")
    units = [dict(zip(fields, row, strict=True)) for row in rows]
    return {**cursor, "units": units}


class Collector(Downloads):
    def __init__(self, project):
        self.project_id, self.job_key = project, project + "-v1"
        self.source, self.capability = SOURCES[project], "collector." + project.replace("-", "_")
        self.dataset = NAV_DATASET if self.source == "ttjj" else SHARE_DATASET
        self.url = dict(sse=SSE_URL, szse=SZSE_URL, ttjj=NAV_URL)[self.source]
        self.domains = (
            ("eastmoney.com",)
            if self.source == "ttjj"
            else (self.source + ".com.cn",)
            if self.source == "sse"
            else ("szse.cn",)
        )
        self.referer = PAGES[self.source].format(code="510300")
        self.manifest = PluginManifest(
            self.capability,
            project,
            requires=(
                "http.fetch",
                "ingest.publish",
                "etf.fundamentals.query",
                "archive.confirmation",
                "collection.records",
            ),
            provides=(self.capability,),
        )
        self.request_retries = 2
        self.stats = dict(status="stopped")

    async def start(self, context):
        self.http, self.ingest = context.get("http.fetch"), context.get("ingest.publish")
        self.query, self.confirmation = (
            context.get("etf.fundamentals.query"),
            context.get("archive.confirmation"),
        )
        self.records = context.get("collection.records")
        self.stats["status"] = "idle"
        return {self.capability: self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))["revision"]

    @measured_run
    async def execute(
        self,
        *,
        fresh=False,
        baseline_revision=0,
        codes=None,
        start=None,
        end=None,
        sample_dates=None,
    ):
        self.stats.update(
            status="planning",
            requests=0,
            response_bytes=0,
            wire_bytes=0,
            collected=0,
            queued_messages=0,
            queued_bytes=0,
            error="",
        )
        stage = "plan"
        try:
            request = dict(codes=codes, start=start, end=end, sample_dates=sample_dates)
            scope = digest(request)
            state = await self.ingest.checkpoint(self.job_key)
            cursor = unpack_cursor(state["cursor"])
            if state["revision"] > baseline_revision and cursor.get("phase") == "complete":
                return state["cursor"]
            if cursor and cursor.get("contract") != CONTRACT:
                raise ValueError("ETF断点版本改变，须显式维护")
            if cursor.get("phase") == "complete":
                cursor = {}
            if cursor and cursor.get("scope") != scope:
                raise ValueError("ETF请求范围与未完成断点冲突")
            if not cursor:
                plan = await self.query.plan(
                    self.source,
                    codes=codes,
                    start=start,
                    end=end,
                    sample_dates=sample_dates,
                    fresh=fresh,
                )
                cursor = dict(
                    contract=CONTRACT,
                    scope=scope,
                    phase="fetch",
                    batch=uuid4().hex,
                    units=plan["units"],
                    recent=plan["recent"],
                    catalog_hash=plan.get("catalog_hash"),
                    index=0,
                    pages=0,
                    collected=0,
                )
                pack_cursor(cursor)  # Reject an oversized frozen plan before any source request.
            self.stats["total_units"] = len(cursor["units"])
            if cursor["phase"] == "fetch":
                remaining = [dict(u) for u in cursor["units"][cursor["index"] :]]
                if remaining and self.source == "ttjj" and cursor.get("next_year"):
                    remaining[0]["start"] = max(remaining[0]["start"], f"{cursor['next_year']}-01-01")
                async with self.reads(remaining) as reads:
                    async for offset, result in reads:
                        stage = "source_validation"
                        rows, observed = await result.resolve()
                        unit = remaining[offset]
                        if self.source != "ttjj" and not rows and unit["date"] in cursor["recent"]:
                            raise ValueError("最近交易日ETF份额尚未发布，保留待补")
                        chunks = (
                            years(unit["start"], unit["through"])
                            if self.source == "ttjj"
                            else [(None, None)]
                        )
                        for chunk_index, (first, last) in enumerate(chunks):
                            payload = dict(page=cursor["pages"] + 1)
                            if self.source == "ttjj":
                                payload.update(
                                    code=unit["code"],
                                    start=first,
                                    through=last,
                                    rows=[r for r in rows if first <= r[0] <= last],
                                )
                                key = unit["code"] + ":" + first[:4]
                            else:
                                payload.update(date=unit["date"], rows=rows)
                                key = unit["date"]
                            if len(json.dumps(payload, ensure_ascii=False).encode()) > MAX_BYTES:
                                raise ValueError("ETF完整消息超过2MiB，拒绝截断")
                            e = make_envelope(
                                source=self.source,
                                dataset=self.dataset,
                                business_key=key,
                                job_key=self.job_key,
                                batch_id=cursor["batch"],
                                run_id=cursor["batch"],
                                schema_version=CONTRACT,
                                payload=payload,
                            )
                            envelope = e.model_copy(
                                update=dict(
                                    observed_at=observed,
                                    available_at=None,
                                    source_url=PAGES[self.source].format(code=unit.get("code", "")[:6]),
                                )
                            )
                            done = chunk_index == len(chunks) - 1
                            following = {
                                **cursor,
                                "index": cursor["index"] + int(done),
                                "next_year": 0 if done else int(first[:4]) + 1,
                                "pages": cursor["pages"] + 1,
                                "collected": cursor["collected"] + len(payload["rows"]),
                            }
                            if following["index"] == len(cursor["units"]):
                                following["phase"] = "awaiting_archive"
                            stage = "queue_publish"
                            state = await publish_with_capacity(
                                self.ingest,
                                self.stats,
                                [envelope],
                                job_key=self.job_key,
                                expected_revision=state["revision"],
                                cursor=pack_cursor(following),
                            )
                            cursor = unpack_cursor(state["cursor"])
                        self.stats.update(
                            status="collecting",
                            collected=cursor["collected"],
                            completed_units=cursor["index"],
                            pages=cursor["pages"],
                        )
            if cursor["pages"]:
                stage = "archive_confirmation"
                self.stats["status"] = "awaiting_archive"
                await wait_for_archive(
                    partial(
                        self.confirmation.page_status,
                        self.source,
                        self.job_key,
                        self.project_id,
                        cursor["batch"],
                        cursor["pages"],
                    ),
                    retry_seconds=1,
                )
            cursor = {**cursor, "phase": "complete"}
            await self.ingest.advance_checkpoint(
                job_key=self.job_key, expected_revision=state["revision"], cursor=pack_cursor(cursor)
            )
            self.stats["status"] = "complete"
            return pack_cursor(cursor)
        except asyncio.CancelledError:
            self.stats["status"] = "paused"
            raise
        except Exception as exc:
            self.stats.update(status="error", error=self.records.sanitize_text(exc))
            if await record_error_safely(
                self.records,
                self.stats,
                self.project_id,
                exc,
                stage=stage,
                unavailable_message="ETF采集错误记录暂不可用",
            ):
                exc.diagnostic_recorded = True
            raise

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
