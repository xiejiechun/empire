"""Annual backfill and recent revisions on shared ordered publication."""

import asyncio
import hashlib
from datetime import UTC, datetime
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.index_prices import BASE, JOB, PROJECT, url
from empire.contracts.plugin import PluginManifest
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.ths_index_prices_source import annual, recent
from empire.plugins.collectors.ths_session import ThsSession
from empire.plugins.datasets.indices import digest


class ThsIndexPriceCollector:
    manifest = PluginManifest(
        "collector.ths_index_prices",
        "同花顺指数历史日行情",
        requires=(
            "http.fetch",
            "ingest.publish",
            "index.prices.query",
            "archive.confirmation",
            "collection.records",
        ),
        provides=("collector.ths_index_prices",),
        description="逐年补缺及last近期修订；年度独立并行归档",
    )

    def __init__(self):
        self.source, self.project_id, self.job_key = "ths", PROJECT, JOB
        self.request_retries, self.selected_codes = 2, None
        self.session = None
        self.stats = {"status": "stopped", "collected": 0}

    async def start(self, context):
        self.http, self.ingest = context.get("http.fetch"), context.get("ingest.publish")
        self.query = context.get("index.prices.query")
        self.confirmation, self.records = (
            context.get("archive.confirmation"),
            context.get("collection.records"),
        )
        self.stats["status"] = "idle"
        return {"collector.ths_index_prices": self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))["revision"]

    async def fetch(self, code, unit="last", snapshot=None, *, reservation=None):
        await wait_for_capacity(self.ingest, self.stats)
        if self.session is None:
            self.session = ThsSession()
        response = await self.http.request(
            "GET",
            url(code, unit),
            allowed_domains=("10jqka.com.cn",),
            headers=self.session.headers("https://q.10jqka.com.cn/zs/"),
            project_id=PROJECT,
            policy=self.http.response_policy("generic"),
            reservation=reservation,
            max_retries=self.request_retries,
            allow_not_found=unit == "last",
            retry_not_found=unit != "last",
        )

        async def consume():
            try:
                if unit == "last" and response.status_code == 404:
                    return None
                source = response.content.decode("utf8")
                return (
                    recent(source, code) if unit == "last" else annual(source, code, unit, snapshot)
                )
            except (ValueError, TypeError, KeyError, UnicodeError) as exc:
                body = response.content
                exc.diagnostic_recorded = await record_error_safely(
                    self.records,
                    self.stats,
                    PROJECT,
                    exc,
                    stage="source_validation",
                    unavailable_message="指数日线错误样本暂未写入Redis",
                    fields=dict(
                        request_url=url(code, unit),
                        status_code=response.status_code,
                        raw_body=body[:65536],
                        observed_bytes=len(body),
                        body_sha256=hashlib.sha256(body).hexdigest(),
                        metadata=getattr(exc, "source_metadata", {}),
                    ),
                )
                raise
            finally:
                if reservation is None:
                    response.close()

        return DeferredResponse(response, consume) if reservation is not None else await consume()

    async def publish(self, state, cursor, dataset, code, payload, *, observed):
        page = cursor["pages"] + 1
        cursor = {
            **cursor,
            "pages": page,
            "collected": cursor["collected"] + len(payload.get("rows", [])),
        }
        identity = code + (":status" if dataset.endswith("status") else ":" + str(payload["year"]))
        e = make_envelope(
            source="ths",
            dataset=dataset,
            business_key=identity,
            job_key=JOB,
            batch_id=cursor["batch_id"],
            run_id=cursor["batch_id"],
            payload=dict(page=page, code=code, **payload),
        )
        e = e.model_copy(
            update={
                "observed_at": observed,
                "source_url": url(code, payload.get("year", "last")),
                "available_at": None,
            }
        )
        result = await publish_with_capacity(
            self.ingest,
            self.stats,
            [e],
            job_key=JOB,
            expected_revision=state["revision"],
            cursor=cursor,
        )
        return result, cursor

    async def execute(self, *, fresh=False, baseline_revision=0):
        stage = "source_validation"
        try:
            state = await self.ingest.checkpoint(JOB)
            cursor = state["cursor"]
            if (
                state["revision"] > baseline_revision
                and cursor.get("phase") == "complete"
                and not fresh
            ):
                return cursor
            catalog = await self.query.catalog(self.selected_codes)
            names = {r["code"]: r["name"] for r in catalog}
            if cursor.get("phase") not in ("collecting", "awaiting_archive"):
                if not catalog:
                    raise ValueError("尚无同花顺指数目录，请先采集当前指数及成分")
                cursor = dict(
                    phase="collecting",
                    codes=list(names),
                    next_index=0,
                    next_year=1990,
                    snapshot_hash="",
                    pages=0,
                    collected=0,
                    batch_id=uuid4().hex,
                    fresh=bool(fresh),
                    unavailable=0,
                )
            self.stats.update(
                status="collecting",
                error="",
                total_units=len(cursor["codes"]),
                completed_units=cursor["next_index"],
                collected=cursor["collected"],
            )
            if cursor["phase"] == "collecting":
                for i in range(cursor["next_index"], len(cursor["codes"])):
                    code = cursor["codes"][i]
                    self.stats.update(current_security=names.get(code, code))
                    stage = "source_validation"
                    observed = datetime.now(UTC)
                    snapshot = await self.fetch(code)
                    status = dict(
                        name=names.get(code, code),
                        available=snapshot is not None,
                        snapshot={k: snapshot[k] for k in ("start", "end", "years", "total")}
                        if snapshot
                        else {},
                    )
                    checksum = digest(snapshot)
                    if checksum != cursor["snapshot_hash"]:
                        cursor = {**cursor, "next_year": 1990, "snapshot_hash": checksum}
                    stage = "queue_publish"
                    state, cursor = await self.publish(
                        state, cursor, "index.price.status", code, status, observed=observed
                    )
                    if snapshot is not None:
                        # Query only yearly proofs, never wait for previously queued archival.
                        heads = await self.query.year_heads(code)
                        recent_years = {r[0][:4] for r in snapshot["rows"]}
                        # A pending current-day source must not replace already archived daily data
                        # or downgrade its annual proof. Recheck that year on the next round.
                        deferred_years = {
                            y for y, head in heads.items()
                            if snapshot.get("deferred_day", "")[:4] == y
                            and head["last_date"] > snapshot["end"]
                        }
                        years = [
                            int(y)
                            for y, n in sorted(snapshot["years"].items())
                            if int(y) >= cursor["next_year"]
                            and y not in deferred_years
                            and (
                                cursor["fresh"]
                                or not heads.get(y, {}).get("complete")
                                or heads[y]["source_count"] != n
                                or (
                                    y in recent_years
                                    and heads[y]["last_date"] < snapshot["rows"][0][0]
                                )
                            )
                        ]

                        async def download(year, *, reservation):
                            return await self.fetch(code, year, snapshot, reservation=reservation)

                        async with prefetch_units(
                            self,
                            years,
                            download,
                            url=BASE,
                            domains=("10jqka.com.cn",),
                            item_name="年份",
                        ) as reads:
                            async for j, read in reads:
                                stage = "source_validation"
                                rows = await read.resolve()
                                year = years[j]
                                cursor = {**cursor, "next_year": year + 1}
                                stage = "queue_publish"
                                state, cursor = await self.publish(
                                    state,
                                    cursor,
                                    "index.price.year",
                                    code,
                                    dict(
                                        year=year,
                                        mode="full",
                                        source_count=snapshot["years"][str(year)],
                                        start=snapshot["start"],
                                        end=snapshot["end"],
                                        rows=rows,
                                    ),
                                    observed=observed,
                                )
                                self.stats.update(
                                    collected=cursor["collected"],
                                    pages=cursor["pages"],
                                    current_date=str(year),
                                )
                        for year in sorted(recent_years):
                            if year in deferred_years:
                                continue
                            if int(year) in years:
                                continue  # Same last snapshot already validated against the full year.
                            rows = [r for r in snapshot["rows"] if r[0][:4] == year]
                            state, cursor = await self.publish(
                                state,
                                cursor,
                                "index.price.year",
                                code,
                                dict(
                                    year=int(year),
                                    mode="recent",
                                    source_count=snapshot["years"][year],
                                    start=snapshot["start"],
                                    end=snapshot["end"],
                                    rows=rows,
                                ),
                                observed=observed,
                            )
                    else:
                        cursor["unavailable"] += 1
                    cursor = {**cursor, "next_index": i + 1, "next_year": 1990, "snapshot_hash": ""}
                    if i + 1 == len(cursor["codes"]):
                        cursor["phase"] = "awaiting_archive"
                    state = await self.ingest.advance_checkpoint(
                        job_key=JOB, expected_revision=state["revision"], cursor=cursor
                    )
                    self.stats.update(completed_units=i + 1, unavailable=cursor["unavailable"])
            stage = "archive_confirmation"
            self.stats["status"] = "awaiting_archive"
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
            self.stats.update(status="complete", error="")
            return {k: v for k, v in cursor.items() if k != "codes"}
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
                unavailable_message="指数行情错误记录暂不可用；已入队断点保留",
            )
            raise

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
