"""Full date discovery, bounded parallel detail prefetch, independent archive."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from functools import partial
from uuid import uuid4

from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.features.hot_list.contract import CONTRACT, DATASET, JOB, PROJECT, day, digest
from empire.features.hot_list.source import PAGE, URL, params, parse_detail, parse_directory
from empire.plugins.collection.unit_prefetch import DeferredResponse, prefetch_units
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)


class HotListCollector:
    project_id, job_key, source = PROJECT, JOB, "tdx"
    manifest = PluginManifest(
        "collector.tdx_hot_list",
        "个股龙虎榜采集",
        requires=(
            "http.fetch",
            "ingest.publish",
            "hot_list.query",
            "archive.confirmation",
            "collection.records",
        ),
        provides=("collector.tdx_hot_list",),
        description="全历史目录、近90日回查、每天19:30",
    )

    def __init__(self):
        self.request_retries = 2
        self.stats = dict(status="stopped", collected=0, requests=0)

    async def start(self, context):
        self.http, self.ingest = context.get("http.fetch"), context.get("ingest.publish")
        self.query, self.confirmation = (
            context.get("hot_list.query"),
            context.get("archive.confirmation"),
        )
        self.records = context.get("collection.records")
        self.stats["status"] = "idle"
        return {"collector.tdx_hot_list": self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(JOB))["revision"]

    async def fetch(self, item, *, reservation=None):
        code, requested, through = item
        await wait_for_capacity(self.ingest, self.stats)
        observed = datetime.now(UTC)
        response = await self.http.request(
            "POST",
            URL,
            content=json.dumps({"Params": params(code, requested)}).encode(),
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
                body = json.loads(response.content, parse_float=Decimal)
                return (
                    parse_directory(body, code, through)
                    if requested is None
                    else parse_detail(body)
                ), observed
            except (ValueError, TypeError, KeyError) as exc:
                raw = response.content
                exc.diagnostic_recorded = await record_error_safely(
                    self.records,
                    self.stats,
                    PROJECT,
                    exc,
                    stage="source_validation",
                    unavailable_message="龙虎榜来源诊断暂不可用",
                    fields=dict(
                        request_url=URL,
                        status_code=response.status_code,
                        raw_body=raw[:65536],
                        observed_bytes=len(raw),
                        body_sha256=hashlib.sha256(raw).hexdigest(),
                        metadata={"params": params(code, requested)},
                    ),
                )
                raise

        return DeferredResponse(response, consume)

    def envelope(self, cursor, mode, code, stamp, value, observed):
        e = make_envelope(
            source="tdx",
            dataset=DATASET,
            business_key=mode + ":" + code + ":" + stamp,
            job_key=JOB,
            batch_id=cursor["batch_id"],
            run_id=cursor["batch_id"],
            schema_version=CONTRACT,
            payload=dict(page=cursor["pages"], mode=mode, code=code, date=stamp, value=value),
        )
        return e.model_copy(
            update={"observed_at": observed, "source_url": PAGE, "available_at": None}
        )

    async def publish(self, state, cursor, mode, code, stamp, value, observed):
        return await publish_with_capacity(
            self.ingest,
            self.stats,
            [self.envelope(cursor, mode, code, stamp, value, observed)],
            job_key=JOB,
            expected_revision=state["revision"],
            cursor=cursor,
        )

    async def execute(self, *, fresh=False, baseline_revision=0, codes=None, start=None, end=None):
        stage = "plan"
        try:
            if start:
                day(start)
            if end:
                day(end)
            if start and end and start > end:
                raise ValueError("龙虎榜起止日期倒置")
            state = await self.ingest.checkpoint(JOB)
            cursor, progressed = state["cursor"], state["revision"] > baseline_revision
            if progressed and cursor.get("phase") == "complete":
                return cursor
            if cursor and cursor.get("contract") != CONTRACT:
                raise ValueError("龙虎榜断点契约改变，须显式维护")
            if cursor.get("phase") != "awaiting_archive":
                pool = await self.query.securities(codes)
                scope = digest(pool)
                if (fresh and not progressed) or cursor.get("phase") == "complete":
                    cursor = {}
                if cursor and (
                    cursor["scope_hash"] != scope
                    or cursor["start"] != (start or "")
                    or cursor["end"] != (end or "")
                ):
                    raise ValueError("龙虎榜范围与断点冲突，须重新初始化")
                if not cursor:
                    cursor = dict(
                        phase="fetch",
                        contract=CONTRACT,
                        batch_id=uuid4().hex,
                        index=0,
                        pages=0,
                        collected=0,
                        securities=len(pool),
                        scope_hash=scope,
                        start=start or "",
                        end=end or "",
                        through=datetime.now(CHINA).date().isoformat(),
                        force=bool(fresh),
                        directory_hash="",
                        last_date="",
                    )
                self.stats.update(status="collecting", error="", requests=0, total_units=len(pool))
                for index in range(cursor["index"], len(pool)):
                    code = pool[index]
                    self.stats.update(current_security=code, completed_units=index)
                    async with prefetch_units(
                        self,
                        [(code, None, cursor["through"])],
                        self.fetch,
                        url=URL,
                        domains=("tdx.com.cn",),
                        item_name="日期目录",
                    ) as reads:
                        async for _, read in reads:
                            dates, observed = await read.resolve()
                    checksum = digest(dates)
                    if cursor["directory_hash"] and cursor["directory_hash"] != checksum:
                        raise ValueError("龙虎榜中断证券目录已修订，须重新初始化，不混合集合")
                    if not cursor["directory_hash"]:
                        cursor = {
                            **cursor,
                            "directory_hash": checksum,
                            "pages": cursor["pages"] + 1,
                        }
                        state = await self.publish(
                            state,
                            cursor,
                            "directory",
                            code,
                            "",
                            dict(dates=dates, through=cursor["through"]),
                            observed,
                        )
                    existing = await self.query.day_heads(code)
                    review_start = (
                        datetime.fromisoformat(cursor["through"]).date() - timedelta(days=89)
                    ).isoformat()
                    chosen = [
                        d
                        for d in dates
                        if (not cursor["last_date"] or d < cursor["last_date"])
                        and (not start or d >= start)
                        and (not end or d <= end)
                        and (
                            cursor["force"]
                            or bool(start or end)
                            or d >= review_start
                            or existing.get(d, {}).get("detail_status") != "present"
                        )
                    ]
                    async with prefetch_units(
                        self,
                        [(code, d, cursor["through"]) for d in chosen],
                        self.fetch,
                        url=URL,
                        domains=("tdx.com.cn",),
                        item_name="榜单日期",
                    ) as reads:
                        async for number, read in reads:
                            stage = "source_validation"
                            value, observed = await read.resolve()
                            stamp = chosen[number]
                            following = {
                                **cursor,
                                "last_date": stamp,
                                "pages": cursor["pages"] + 1,
                                "collected": cursor["collected"] + len(value["seats"]),
                            }
                            stage = "queue_publish"
                            state = await self.publish(
                                state, following, "detail", code, stamp, value, observed
                            )
                            cursor = state["cursor"]
                            self.stats.update(collected=cursor["collected"], pages=cursor["pages"])
                    following = {
                        **cursor,
                        "index": index + 1,
                        "directory_hash": "",
                        "last_date": "",
                        "pages": cursor["pages"] + 1,
                    }
                    state = await self.publish(
                        state,
                        following,
                        "finish",
                        code,
                        "",
                        dict(directory_hash=checksum, count=len(dates), through=cursor["through"]),
                        datetime.now(UTC),
                    )
                    cursor = state["cursor"]
                cursor = {**cursor, "pages": cursor["pages"] + 1, "phase": "awaiting_archive"}
                state = await self.publish(
                    state,
                    cursor,
                    "manifest",
                    "",
                    "",
                    {k: cursor[k] for k in ("scope_hash", "securities", "through")},
                    datetime.now(UTC),
                )
            stage = "archive_confirmation"
            self.stats.update(
                status="awaiting_archive", pages=cursor["pages"], collected=cursor["collected"]
            )
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
                unavailable_message="龙虎榜错误记录暂不可用；失败位置保留",
            )
            raise

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
