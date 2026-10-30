"""Bounded security prefetch; publication precedes independent whole-round archive wait."""

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
from empire.features.market_margin.contract import CONTRACT, DATASET, JOB, PROJECT, digest, pack
from empire.features.market_margin.source import PAGE, URL, parse
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)


class MarketMarginCollector:
    project_id, job_key, source = PROJECT, JOB, "ths"
    manifest = PluginManifest(
        "collector.ths_market_margin",
        "市场融资融券采集",
        requires=(
            "http.fetch",
            "ingest.publish",
            "market_margin.query",
            "archive.confirmation",
            "collection.records",
        ),
        provides=("collector.ths_market_margin",),
        description="四市场完整序列；每日全量核验例外",
    )

    def __init__(self):
        self.request_retries = 2
        self.stats = dict(status="stopped", collected=0, requests=0)

    async def start(self, context):
        self.http, self.ingest = context.get("http.fetch"), context.get("ingest.publish")
        self.query, self.confirmation = (
            context.get("market_margin.query"),
            context.get("archive.confirmation"),
        )
        self.records = context.get("collection.records")
        self.stats["status"] = "idle"
        return {"collector.ths_market_margin": self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))["revision"]

    async def fetch(self, item, *, reservation=None):
        code, through = item
        await wait_for_capacity(self.ingest, self.stats)
        observed = datetime.now(UTC)
        response = await self.http.request(
            "GET",
            URL.format(code=code),
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Referer": PAGE,
            },
            allowed_domains=("10jqka.com.cn",),
            project_id=PROJECT,
            policy=self.http.response_policy("generic"),
            max_retries=self.request_retries,
            reservation=reservation,
        )
        self.stats["requests"] += 1

        async def consume():
            try:
                return parse(
                    json.loads(response.content, parse_float=Decimal), through, code
                ), observed
            except (ValueError, TypeError, KeyError) as exc:
                raw = response.content
                exc.diagnostic_recorded = await record_error_safely(
                    self.records,
                    self.stats,
                    PROJECT,
                    exc,
                    stage="source_validation",
                    unavailable_message="融资融券诊断暂不可用",
                    fields=dict(
                        request_url=URL.format(code=code),
                        status_code=response.status_code,
                        raw_body=raw[:65536],
                        observed_bytes=len(raw),
                        body_sha256=hashlib.sha256(raw).hexdigest(),
                        metadata={"market": code},
                    ),
                )
                raise

        return DeferredResponse(response, consume)

    async def execute(self, *, fresh=False, baseline_revision=0, markets=None):
        stage = "plan"
        try:
            state = await self.ingest.checkpoint(JOB)
            cursor, progressed = state["cursor"], state["revision"] > baseline_revision
            if progressed and cursor.get("phase") == "complete":
                return cursor
            if cursor and cursor.get("contract") != CONTRACT:
                raise ValueError("融资融券断点契约改变，须显式维护")
            if cursor.get("phase") != "awaiting_archive":
                pool = await self.query.markets(markets)
                if (fresh and not progressed) or cursor.get("phase") == "complete":
                    cursor = {}
                if cursor and cursor["scope_hash"] != digest(pool):
                    raise ValueError("融资融券市场范围与未完成断点冲突，须重新初始化")
                if not cursor:
                    cursor = dict(
                        phase="fetch",
                        contract=CONTRACT,
                        scope_hash=digest(pool),
                        batch_id=uuid4().hex,
                        index=0,
                        pages=0,
                        collected=0,
                        securities=len(pool),
                        through=datetime.now(CHINA).date().isoformat(),
                    )
                self.stats.update(status="collecting", error="", requests=0, total_units=len(pool))
                pending = [(code, cursor["through"]) for code in pool[cursor["index"] :]]
                async with prefetch_units(
                    self,
                    pending,
                    self.fetch,
                    url=URL.format(code="99"),
                    domains=("10jqka.com.cn",),
                    item_name="市场",
                ) as reads:
                    async for number, read in reads:
                        stage = "source_validation"
                        rows, observed = await read.resolve()
                        code = pending[number][0]
                        following = {
                            **cursor,
                            "pages": cursor["pages"] + 1,
                            "index": cursor["index"] + 1,
                            "collected": cursor["collected"] + len(rows),
                        }
                        if following["index"] == len(pool):
                            following["phase"] = "awaiting_archive"
                        envelope = make_envelope(
                            source="ths",
                            dataset=DATASET,
                            business_key=code,
                            job_key=JOB,
                            batch_id=cursor["batch_id"],
                            run_id=cursor["batch_id"],
                            schema_version=CONTRACT,
                            payload=dict(
                                page=following["pages"],
                                code=code,
                                through=cursor["through"],
                                rows=pack(rows),
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
                            completed_units=cursor["index"],
                            current_market=code,
                        )
            stage = "archive_confirmation"
            self.stats.update(status="awaiting_archive", collected=cursor["collected"])
            await wait_for_archive(
                partial(
                    self.confirmation.page_status,
                    "ths",
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
            self.stats.update(status="complete", error="", completed_units=cursor["securities"])
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
                unavailable_message="融资融券错误记录暂不可用；失败位置保留",
            )
            raise

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
