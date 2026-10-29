"""Bounded date prefetch, atomic progress, and independent whole-round archiving."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.features.industry_margin.contract import (
    CONTRACT,
    DATASET,
    JOB,
    PROJECT,
    START,
    day,
    digest,
    plan,
)
from empire.features.industry_margin.source import PAGE, URL, params, parse
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)


class IndustryMarginCollector:
    project_id, job_key, source = PROJECT, JOB, "tdx"
    manifest = PluginManifest(
        "collector.tdx_industry_margin",
        "行业融资融券采集",
        requires=(
            "http.fetch",
            "ingest.publish",
            "industry_margin.query",
            "archive.confirmation",
            "collection.records",
        ),
        provides=("collector.tdx_industry_margin",),
        description="2016年起完整日期补缺及分层修订回查",
    )

    def __init__(self):
        self.request_retries = 2
        self.stats = dict(status="stopped", collected=0, requests=0)

    async def start(self, context):
        self.http, self.ingest = context.get("http.fetch"), context.get("ingest.publish")
        self.query, self.confirmation = (
            context.get("industry_margin.query"),
            context.get("archive.confirmation"),
        )
        self.records = context.get("collection.records")
        self.stats["status"] = "idle"
        return {"collector.tdx_industry_margin": self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))["revision"]

    async def fetch(self, stamp, *, reservation=None):
        await wait_for_capacity(self.ingest, self.stats)
        observed = datetime.now(UTC)
        response = await self.http.request(
            "POST",
            URL,
            content=json.dumps({"Params": params(stamp)}).encode(),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": PAGE,
            },
            allowed_domains=("tdx.com.cn",),
            project_id=PROJECT,
            policy=self.http.response_policy("generic"),
            max_retries=self.request_retries,
            reservation=reservation,
        )
        self.stats["requests"] += 1

        async def consume():
            try:
                return parse(
                    json.loads(response.content, parse_float=Decimal),
                    latest=stamp is None,
                    through=observed.astimezone(CHINA).date().isoformat(),
                ), observed
            except (ValueError, TypeError, KeyError) as exc:
                raw = response.content
                exc.diagnostic_recorded = await record_error_safely(
                    self.records,
                    self.stats,
                    PROJECT,
                    exc,
                    stage="source_validation",
                    unavailable_message="行业融资融券来源诊断暂不可用",
                    fields=dict(
                        request_url=URL,
                        status_code=response.status_code,
                        raw_body=raw[:65536],
                        observed_bytes=len(raw),
                        body_sha256=hashlib.sha256(raw).hexdigest(),
                        metadata={"params": params(stamp)},
                    ),
                )
                raise

        return DeferredResponse(response, consume)

    async def execute(
        self, *, fresh=False, baseline_revision=0, start=None, end=None, sample_dates=None
    ):
        stage = "plan"
        try:
            first = day(start or START)
            if end:
                day(end)
            if sample_dates is not None:
                if (
                    not isinstance(sample_dates, (list, tuple))
                    or not sample_dates
                    or len(sample_dates) > 1000
                ):
                    raise ValueError("行业融资融券指定日期范围无效")
                if len(set(sample_dates)) != len(sample_dates):
                    raise ValueError("行业融资融券指定日期重复")
                sample_dates = sorted(day(d) for d in sample_dates)
            scope = digest([first, end, sample_dates])
            state = await self.ingest.checkpoint(JOB)
            cursor, progressed = state["cursor"], state["revision"] > baseline_revision
            if progressed and cursor.get("phase") == "complete":
                return cursor
            if cursor and cursor.get("contract") != CONTRACT:
                raise ValueError("行业融资融券断点契约改变，须显式维护")
            if cursor.get("phase") != "awaiting_archive":
                if (fresh and not progressed) or cursor.get("phase") == "complete":
                    cursor = {}
                if cursor and cursor["scope_hash"] != scope:
                    raise ValueError("行业融资融券范围与未完成断点冲突")
                if not cursor:
                    async with prefetch_units(
                        self,
                        [None],
                        self.fetch,
                        url=URL,
                        domains=("tdx.com.cn",),
                        item_name="来源日期",
                    ) as reads:
                        async for _, read in reads:
                            latest, _ = await read.resolve()
                    last = min(end, latest) if end else latest
                    if first > last or (
                        sample_dates and (sample_dates[0] < first or sample_dates[-1] > last)
                    ):
                        raise ValueError("行业融资融券请求范围超出来源最新日期")
                    cursor = dict(
                        phase="fetch",
                        contract=CONTRACT,
                        scope_hash=scope,
                        batch_id=uuid4().hex,
                        start=first,
                        end=last,
                        through=datetime.now(CHINA).date().isoformat(),
                        source_latest=latest,
                        last_date="",
                        pages=0,
                        collected=0,
                        force=bool(fresh or start or end or sample_dates),
                    )
                existing = await self.query.covered(cursor["start"], cursor["end"])
                pending = (
                    sample_dates
                    if sample_dates is not None
                    else plan(
                        cursor["start"],
                        cursor["end"],
                        existing,
                        cursor["through"],
                        force=cursor["force"],
                    )
                )
                pending = [d for d in pending if d > cursor["last_date"]]
                self.stats.update(
                    status="collecting", error="", total_units=len(pending) + cursor["pages"]
                )
                async with prefetch_units(
                    self, pending, self.fetch, url=URL, domains=("tdx.com.cn",), item_name="日期"
                ) as reads:
                    async for index, read in reads:
                        stage = "source_validation"
                        rows, observed = await read.resolve()
                        stamp = pending[index]
                        following = {
                            **cursor,
                            "last_date": stamp,
                            "pages": cursor["pages"] + 1,
                            "collected": cursor["collected"] + len(rows),
                        }
                        if index == len(pending) - 1:
                            following["phase"] = "awaiting_archive"
                        envelope = make_envelope(
                            source="tdx",
                            dataset=DATASET,
                            business_key=stamp,
                            job_key=JOB,
                            batch_id=cursor["batch_id"],
                            run_id=cursor["batch_id"],
                            schema_version=CONTRACT,
                            payload=dict(
                                page=following["pages"],
                                date=stamp,
                                rows=rows,
                                source_latest=cursor["source_latest"],
                            ),
                        )
                        envelope = envelope.model_copy(
                            update=dict(observed_at=observed, source_url=PAGE, available_at=None)
                        )
                        stage = "queue_publish"
                        state = await publish_with_capacity(
                            self.ingest,
                            self.stats,
                            [envelope],
                            job_key=JOB,
                            expected_revision=state["revision"],
                            cursor=following,
                        )
                        cursor = state["cursor"]
                        self.stats.update(
                            collected=cursor["collected"],
                            pages=cursor["pages"],
                            completed_units=cursor["pages"],
                        )
            if cursor["pages"]:
                stage = "archive_confirmation"
                self.stats["status"] = "awaiting_archive"
                await wait_for_archive(
                    partial(
                        self.confirmation.page_status,
                        "tdx",
                        JOB,
                        PROJECT,
                        cursor["batch_id"],
                        cursor["pages"],
                    ),
                    retry_seconds=1,
                )
            cursor = {**cursor, "phase": "complete"}
            await self.ingest.advance_checkpoint(
                job_key=JOB, expected_revision=state["revision"], cursor=cursor
            )
            self.stats.update(status="complete", error="")
            return cursor
        except asyncio.CancelledError:
            self.stats["status"] = "paused"
            raise
        except Exception as exc:
            self.stats.update(status="error", error=self.records.sanitize_text(exc))
            await record_error_safely(
                self.records,
                self.stats,
                PROJECT,
                exc,
                stage=stage,
                unavailable_message="行业融资融券错误记录暂不可用；失败位置保留",
            )
            raise

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
