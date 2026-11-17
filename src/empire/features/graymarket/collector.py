"""Complete-day publication, SQL coverage recovery and whole-round confirmation."""

import asyncio
from datetime import UTC, datetime, timedelta
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.contracts.request_cost import measured_run
from empire.core.time import CHINA
from empire.features.graymarket.codec import pack
from empire.features.graymarket.contract import (
    CONTRACT,
    DATASET,
    JOB,
    PROJECT,
    START,
    day,
    digest,
    plan,
)
from empire.features.graymarket.download import GraymarketDownload
from empire.features.graymarket.source import DOMAINS, PAGE, URL
from empire.plugins.collection.unit_prefetch import prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
)


class GraymarketCollector(GraymarketDownload):
    project_id, job_key, source = PROJECT, JOB, "eastmoney"
    manifest = PluginManifest(
        "collector.eastmoney_graymarket",
        "明盘暗盘资金榜采集",
        requires=(
            "http.fetch",
            "ingest.publish",
            "graymarket.query",
            "archive.confirmation",
            "collection.records",
            "redis.store",
        ),
        provides=("collector.eastmoney_graymarket",),
        description="完整交易日补缺及近端回看",
    )

    def __init__(self, intraday=False):
        self.intraday = intraday
        self.request_retries = 2
        self.stats = dict(status="stopped", requests=0, collected=0)

    async def start(self, context):
        self.http, self.ingest = context.get("http.fetch"), context.get("ingest.publish")
        self.query, self.records = (
            context.get("graymarket.query"),
            context.get("collection.records"),
        )
        self.confirmation = context.get("archive.confirmation")
        from empire.features.graymarket.intraday_store import IntradayStore

        self.live_store = IntradayStore(context.get("redis.store"))
        self.stats["status"] = "idle"
        return {"collector.eastmoney_graymarket": self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))["revision"]

    async def discover(self):
        async def fetch(_, *, reservation):
            observed = datetime.now(UTC)
            return await self.read_page(None, 1, reservation=reservation), observed

        async with prefetch_units(
            self, [None], fetch, url=URL, domains=DOMAINS, independent=False, retained_bytes=65536
        ) as reads:
            async for _, read in reads:
                return await read.resolve()
        raise ValueError("资金榜最新日期缺失")

    @measured_run
    async def execute(
        self, *, fresh=False, baseline_revision=0, start=None, end=None, sample_dates=None
    ):
        if self.intraday and start is None and end is None and sample_dates is None:
            from empire.features.graymarket.intraday import dispatch

            try:
                return await dispatch(self, fresh=fresh, baseline_revision=baseline_revision)
            except asyncio.CancelledError:
                self.stats["status"] = "paused"
                raise
            except Exception as exc:
                self.stats.update(status="error", error=self.records.sanitize_text(exc))
                await record_error_safely(self.records, self.stats, PROJECT, exc,
                    stage="intraday_dispatch", unavailable_message="资金榜盘中诊断暂不可用")
                raise
        return await self._execute(fresh=fresh, baseline_revision=baseline_revision,
                                   start=start, end=end, sample_dates=sample_dates)

    async def _execute(
        self, *, fresh=False, baseline_revision=0, start=None, end=None, sample_dates=None,
        planned_dates=None, maintenance_slot=None
    ):
        self.stats.update(storage="mysql", notice="", requests=0, response_bytes=0,
                          wire_bytes=0, queued_messages=0, queued_bytes=0)
        stage, discovered = "plan", None
        try:
            first = day(start or START)
            if first < START:
                raise ValueError("资金榜起点早于声明范围")
            if end:
                day(end)
            if sample_dates is not None:
                if (
                    not isinstance(sample_dates, (list, tuple))
                    or not 1 <= len(sample_dates) <= 1000
                    or len(set(sample_dates)) != len(sample_dates)
                ):
                    raise ValueError("资金榜抽样日期无效")
                sample_dates = sorted(day(d) for d in sample_dates)
            if planned_dates is not None and (not sample_dates or list(planned_dates) != sample_dates):
                raise ValueError("资金榜维护计划与执行范围不一致")
            scope = digest([first, end, sample_dates])
            state = await self.ingest.checkpoint(JOB)
            cursor, progressed = state["cursor"], state["revision"] > baseline_revision
            if progressed and cursor.get("phase") == "complete":
                return cursor
            if cursor and cursor.get("contract") != CONTRACT:
                raise ValueError("资金榜断点契约改变，须显式维护")
            if fresh and not progressed or cursor.get("phase") == "complete":
                cursor = {}
            if cursor and cursor["scope_hash"] != scope:
                raise ValueError("资金榜范围与未完成断点冲突")
            if cursor.get("phase") != "awaiting_archive":
                if not cursor:
                    discovered = await self.discover() if planned_dates is None else None
                    now = datetime.now(CHINA)
                    cutoff = (
                        now.date() if (now.hour, now.minute) >= (15, 30) else now.date() - timedelta(days=1)
                    ).isoformat()
                    latest = discovered[0].date if discovered else sample_dates[-1]
                    last = min(latest, end or latest, cutoff)
                    if first > last:
                        raise ValueError("资金榜暂无声明范围内已结束交易日")
                    cursor = dict(
                        phase="fetch",
                        contract=CONTRACT,
                        scope_hash=scope,
                        batch_id=uuid4().hex,
                        start=first,
                        end=last,
                        source_latest=last,
                        observed_at=(discovered[1] if discovered else datetime.now(UTC)).isoformat(),
                        last_date="",
                        pages=0,
                        collected=0,
                        force=bool(fresh or start or end or sample_dates),
                        request_scope=dict(start=start, end=end, sample_dates=sample_dates),
                        planned=planned_dates is not None,
                        maintenance_slot=maintenance_slot,
                    )
                if cursor.get("planned") and sample_dates:
                    pending = sample_dates
                else:
                    calendar = await self.query.trading_dates(cursor["start"], cursor["end"])
                    if sample_dates is not None and not set(sample_dates) <= set(calendar):
                        raise ValueError("资金榜样本不是范围内已确认交易日")
                    existing = await self.query.covered(cursor["start"], cursor["end"])
                    pending = sample_dates if sample_dates is not None else plan(calendar, existing, force=cursor["force"])
                pending = [d for d in pending if d > cursor["last_date"]]
                self.stats.update(
                    status="collecting", error="", total_units=len(pending) + cursor["pages"]
                )
                async with self.daily_reads(pending, discovered=discovered) as reads:
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
                            source="eastmoney",
                            dataset=DATASET,
                            business_key=stamp,
                            job_key=JOB,
                            batch_id=cursor["batch_id"],
                            run_id=cursor["batch_id"],
                            schema_version=CONTRACT,
                            payload=dict(
                                page=following["pages"],
                                date=stamp,
                                rows=pack(rows),
                                source_latest=cursor["source_latest"],
                            ),
                        )
                        envelope = envelope.model_copy(
                            update=dict(
                                observed_at=datetime.fromisoformat(cursor["observed_at"]),
                                source_url=PAGE,
                                available_at=None,
                            )
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
                            completed_units=cursor["pages"],
                            pages=cursor["pages"],
                        )
            if cursor["pages"]:
                stage = "archive_confirmation"
                self.stats["status"] = "awaiting_archive"
                await wait_for_archive(
                    partial(
                        self.confirmation.page_status,
                        "eastmoney",
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
            recorded = await record_error_safely(
                self.records,
                self.stats,
                PROJECT,
                exc,
                stage=stage,
                unavailable_message="资金榜错误记录暂不可用，失败位置保留",
            )
            if recorded:
                exc.diagnostic_recorded = True
            raise

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
