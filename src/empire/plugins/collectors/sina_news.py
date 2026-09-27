"""Newest-window refresh and durable ID-anchored catch-up of Sina's public flash feed."""
import asyncio
from datetime import UTC, datetime
from functools import partial
from typing import Any
from uuid import uuid4

from empire.contracts.collector import NewsRunResult
from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginManifest
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.datasets.news import news_id, normalize_source

API_URL = "https://app.cj.sina.com.cn/api/news/pc"
PAGE_SIZE = 50


def parse_feed(response, before_id=0):
    body = response.json()
    result = body.get("result") if isinstance(body, dict) else None
    if not isinstance(result, dict) or result.get("status", {}).get("code") != 0:
        raise ValueError("新浪财经新闻接口业务状态异常")
    feed = result.get("data", {}).get("feed")
    if not isinstance(feed, dict) or not isinstance(feed.get("list"), list):
        raise ValueError("新浪财经新闻缺少 feed.list")
    rows = [normalize_source(row) for row in feed["list"]]
    if len(rows) > PAGE_SIZE:
        raise ValueError("新浪财经新闻返回页大小超出请求范围")
    ids = [row["news_id"] for row in rows]
    if any(a <= b for a, b in zip(ids, ids[1:])) or (ids and before_id and ids[0] >= before_id):
        raise ValueError("新浪新闻 ID 重复、逆序或分页游标未前进")
    if ids and (news_id(feed.get("min_id")) != ids[-1] or news_id(feed.get("max_id")) != ids[0]):
        raise ValueError("新浪新闻分页边界与条目 ID 不一致")
    return rows


class SinaNewsCollector:
    manifest = PluginManifest("collector.sina_news", "新浪 7×24 财经新闻",
        requires=("http.fetch", "ingest.publish", "news.schema", "archive.confirmation",
                  "collection.records"),
        provides=("collector.sina_news",), description="全球实时财经新闻直播；按 ID 增量补采、历史去重及近期修订刷新")

    def __init__(self, settings=None):
        self.settings = settings or {}
        self.job_key = "sina-news-v1"
        self.project_id = "sina-news"
        self.source = "sina"
        self.http = self.ingest = self.confirmation = self.records = None
        self.request_retries = 2
        self.stats = {"status": "stopped", "collected": 0}

    async def start(self, context):
        self.http, self.ingest = context.get("http.fetch"), context.get("ingest.publish")
        self.confirmation = context.get("archive.confirmation")
        self.records = context.get("collection.records")
        self.stats["status"] = "idle"
        return {"collector.sina_news": self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))["revision"]

    async def _capacity(self):
        await wait_for_capacity(self.ingest, self.stats)

    async def execute(self, *, fresh=False, baseline_revision=0) -> NewsRunResult:
        response = None
        stage = "checkpoint"
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state["cursor"]
            progressed = state["revision"] > baseline_revision
            if progressed and cursor.get("phase") == "complete":
                return self._result(cursor)
            if not cursor or (fresh and not progressed) or cursor.get("phase") == "complete":
                cursor = {"batch_id": uuid4().hex, "phase": "fetch", "before_id": 0,
                          "high_watermark": 0 if fresh else cursor.get("high_watermark", 0),
                          "upper_id": 0, "pages": 0, "collected": 0, "covered": False,
                          "started_at": datetime.now(UTC).isoformat()}
            while cursor["phase"] == "fetch":
                response = None
                await self._capacity()
                stage = "http_request"
                params = {"page": 1, "size": PAGE_SIZE, "tag": 0}
                if cursor["before_id"]:
                    params.update(id=cursor["before_id"], type=1)
                response = await self.http.request("GET", API_URL, params=params,
                    allowed_domains=("sina.com.cn",), project_id=self.project_id,
                    policy=self.http.response_policy("news"),
                    max_retries=self.request_retries, headers={"Referer": "https://finance.sina.com.cn/7x24/"})
                stage = "news_validation"
                rows = parse_feed(response, cursor["before_id"])
                covered = cursor["covered"] or cursor["high_watermark"] == 0 or any(
                    row["news_id"] <= cursor["high_watermark"] for row in rows)
                if not rows and not covered:
                    stage = "coverage"
                    raise ValueError("来源可见窗口已结束，未接上上次新闻断点；缺口未跳过。可检查后从头重新采集建立最新基线。")
                page = cursor["pages"] + 1
                finished = not rows or covered
                updated = {**cursor, "pages": page, "covered": covered,
                           "before_id": rows[-1]["news_id"] if rows else cursor["before_id"],
                           "upper_id": cursor["upper_id"] or (rows[0]["news_id"] if rows else 0),
                           "collected": cursor["collected"] + len(rows),
                           "phase": "awaiting_archive" if finished else "fetch"}
                event = make_envelope(source=self.source, dataset="news.flash.page", job_key=self.job_key,
                    business_key=f"{cursor['batch_id']}:{page}", run_id=cursor["batch_id"], batch_id=cursor["batch_id"],
                    payload={"page": page, "rows": rows}).model_copy(update={"source_url": API_URL})
                response.close()
                response = None  # Valid raw responses do not enter durable storage.
                stage = "queue_publish"
                state = await publish_with_capacity(
                    self.ingest, self.stats, [event], job_key=self.job_key,
                    expected_revision=state["revision"], cursor=updated,
                )
                cursor = state["cursor"]
                self.stats.update(status=cursor["phase"] if finished else "collecting", error="",
                                  collected=cursor["collected"], pages=cursor["pages"])
            stage = "archive_confirmation"
            self.stats.update(status="awaiting_archive", error="", collected=cursor["collected"], pages=cursor["pages"])
            await wait_for_archive(partial(
                self.confirmation.page_status,
                self.source, self.job_key, self.project_id, cursor["batch_id"], cursor["pages"],
            ), retry_seconds=1)
            cursor = {**cursor, "phase": "complete", "high_watermark": cursor["upper_id"] or cursor["high_watermark"]}
            await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state["revision"], cursor=cursor)
            self.stats.update(status="complete", error="", collected=cursor["collected"], pages=cursor["pages"])
            return self._result(cursor)
        except asyncio.CancelledError:
            self.stats["status"] = "paused"
            raise
        except Exception as exc:
            self.stats.update(status="error", error=self.records.sanitize_text(exc))
            await record_error_safely(
                self.records, self.stats, self.project_id, exc, stage=stage,
                unavailable_message="错误记录暂未写入 Redis；断点保留",
                fields={
                    "raw_body": response.content if response is not None else None,
                    "request_url": str(response.url) if response is not None else API_URL,
                    "status_code": response.status_code if response is not None else None,
                },
            )
            raise

        finally:
            if response is not None:
                response.close()

    def _result(self, cursor: dict[str, Any]) -> NewsRunResult:
        return {"collected": cursor["collected"], "pages": cursor["pages"],
                "high_watermark": cursor["high_watermark"], "batch_id": cursor["batch_id"]}

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
