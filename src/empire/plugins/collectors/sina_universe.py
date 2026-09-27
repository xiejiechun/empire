"""One resumable full traversal of Sina's hs_a stock-list endpoint."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import UTC, datetime
from functools import partial
from time import monotonic
from urllib.parse import urlencode
from uuid import uuid4

from empire.contracts.collector import StockRunResult
from empire.contracts.data import make_envelope
from empire.contracts.plugin import PluginContext, PluginManifest
from empire.plugins.collectors.stock_pages import StockPages
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)

BASE_URL = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/"
DATA_URL = BASE_URL + "Market_Center.getHQNodeData"
COUNT_URL = BASE_URL + "Market_Center.getHQNodeStockCount"


def decode_json(response):
    charset = re.search(r"charset\s*=\s*([\w-]+)", response.headers.get("content-type", ""), re.I)
    declared = charset.group(1).lower() if charset else "utf-8"
    if declared in ("gbk", "gb2312"):
        declared = "gb18030"
    for encoding in dict.fromkeys((declared, "utf-8", "gb18030")):
        try:
            return json.loads(response.content.decode(encoding))
        except (LookupError, UnicodeDecodeError, json.JSONDecodeError):
            continue
    raise ValueError("新浪响应不是可识别的 JSON，游标未推进")


def parse_count(data) -> int:
    if isinstance(data, str) and re.fullmatch(r"[0-9]+", data.strip()):
        data = int(data.strip())
    if type(data) is not int or not 1 <= data <= 100000:
        raise ValueError("新浪股票总数无效；不会用空列表覆盖已有结果")
    return data


class SinaUniverseCollector(StockPages):
    manifest = PluginManifest(
        "collector.sina_universe", "新浪 A 股股票列表",
        requires=("http.fetch", "ingest.publish", "stocks.schema", "archive.confirmation",
                  "collection.records"),
        provides=("collector.sina_universe",),
        description="沪深北股票代码、名称、统一代码与市场；完整分页校验后发布",
    )

    def __init__(self, settings: dict | None = None):
        self.settings = settings or {}
        self.page_size = int(self.settings.get("page_size", 80))
        if not 1 <= self.page_size <= 80:
            raise ValueError("Sina page size must be between 1 and 80")
        self.job_key = "sina-universe-v1"
        self.confirmation = None
        self.context = self.http = self.ingest = None
        self.records = None
        self.project_id = "sina-stocks"
        self.init_diagnostics()
        self._response = None
        self._stage = "collection"
        self.stats = {"status": "stopped", "collected": 0, "expected_count": 0}
        self.request_retries = 2
        self.queue_reservation = None

    async def start(self, context: PluginContext) -> dict:
        self.context = context
        self.http = context.get("http.fetch")
        self.ingest = context.get("ingest.publish")
        self.confirmation = context.get("archive.confirmation")
        self.records = context.get("collection.records")
        self.stats["status"] = "idle"
        return {"collector.sina_universe": self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))["revision"]

    def _error_text(self, error):
        return self.records.sanitize_text(error)

    async def execute(self, *, fresh=False, baseline_revision=0) -> StockRunResult:
        download_started = monotonic()
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state["cursor"]
            progressed = state["revision"] > baseline_revision
            if progressed and cursor.get("phase") == "complete":
                result: StockRunResult = {
                    "snapshot_id": cursor["snapshot_id"],
                    "collected": cursor["collected"],
                    "expected_count": cursor["expected_count"],
                }
            else:
                result = await self._collect(force_new=fresh and not progressed)
            result["download_seconds"] = round(monotonic() - download_started, 3)
            archive_started = monotonic()
            self.stats.update(status="awaiting_archive", error="", **result)
            await wait_for_archive(partial(
                self.confirmation.stock_status,
                "sina", self.job_key, self.project_id, result["snapshot_id"],
            ), retry_seconds=2)
            result["archive_wait_seconds"] = round(monotonic() - archive_started, 3)
            self.stats.update(status="complete", error="")
            return result
        except asyncio.CancelledError:
            self.stats["status"] = "paused"
            raise
        except Exception as exc:
            self.stats.update(status="error", error=self._error_text(exc))
            raise

    async def _capacity(self):
        await wait_for_capacity(
            self.ingest, self.stats, reservation=self.queue_reservation,
            error_text=self._error_text,
        )

    def _capture_response(self, response):
        content = response.content
        self._response.update(raw_body=content[:65536], status_code=response.status_code,
                              observed_bytes=len(content), body_sha256=hashlib.sha256(content).hexdigest())

    async def _get_response(self, url, params, *, reservation=None, policy=None):
        await self._capacity()
        self._stage = "http_request"
        self._response = {"request_url": url + "?" + urlencode(params),
                          "metadata": {"params": params}}
        try:
            response = await self.http.request(
                "GET", url, params=params, allowed_domains=("sina.com.cn",),
                project_id=self.project_id,
                max_retries=self.request_retries,
                policy=policy if policy is not None else self.http.response_policy("stocks"), reservation=reservation,
                headers={"Referer": "https://vip.stock.finance.sina.com.cn/mkt/"},
            )
        except Exception as exc:
            failed = getattr(exc, "response", None)
            if failed is not None:
                self._capture_response(failed)
            raise
        return response

    async def _get(self, url, params):
        response = await self._get_response(url, params)
        try:
            self._capture_response(response)
            self._stage = "json_decode"
            return decode_json(response)
        finally:
            response.close()

    async def _page_response(self, page, page_size, *, reservation=None, policy=None):
        return await self._get_response(DATA_URL, {
            "page": page, "num": page_size, "sort": "symbol", "asc": 0,
            "node": "hs_a", "symbol": "", "_s_r_a": "sort",
        }, reservation=reservation, policy=policy)

    def _decode_page(self, response):
        self._stage = "json_decode"
        data = decode_json(response)
        # Some Sina deployments use JSON null for the page after the end.
        self._stage = "page_validation"
        if data is None:
            return []
        if not isinstance(data, list):
            raise ValueError("新浪分页返回错误对象而非股票数组，游标未推进")
        return data

    async def _page(self, page, page_size):
        response = await self._page_response(page, page_size)
        try:
            self._capture_response(response)
            return self._decode_page(response)
        finally:
            response.close()

    async def _publish(self, dataset, state, cursor, extra, page_id):
        # Once validated, only normalized business fields are retained in Redis.
        self._response = None
        self._stage = "queue_publish"
        common = {k: cursor[k] for k in (
            "snapshot_id", "started_at", "expected_count", "page_size", "node"
        )}
        event = make_envelope(
            source="sina", dataset=dataset, business_key=f"{cursor['snapshot_id']}:{page_id}",
            job_key=self.job_key, run_id=cursor["snapshot_id"], batch_id=cursor["snapshot_id"],
            payload={**common, **extra},
        ).model_copy(update={"source_url": DATA_URL if dataset.endswith("page") else COUNT_URL})
        result = await publish_with_capacity(
            self.ingest, self.stats, [event], job_key=self.job_key,
            expected_revision=state["revision"], cursor=cursor,
            reservation=self.queue_reservation, error_text=self._error_text,
        )
        self.stats.update(snapshot_id=cursor["snapshot_id"], collected=cursor["collected"],
                          expected_count=cursor["expected_count"], next_page=cursor["next_page"])
        return result

    async def _collect(self, force_new=False) -> StockRunResult:
        self._response = None
        self._stage = "checkpoint"
        try:
            return await self._collect_pages(force_new=force_new)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if self.records:
                await record_error_safely(
                    self.records, self.stats, self.project_id, exc, stage=self._stage,
                    unavailable_message="错误记录暂未写入 Redis，恢复连接后重试采集",
                    fields=self._response,
                )
            raise
        finally:
            if self.queue_reservation is not None:
                await asyncio.shield(self.queue_reservation.release())
                self.queue_reservation = None
            self._response = None

    async def _count(self):
        data = await self._get(COUNT_URL, {"node": "hs_a"})
        self._stage = "count_validation"
        return parse_count(data)

    async def _collect_pages(self, force_new=False) -> StockRunResult:
        state = await self.ingest.checkpoint(self.job_key)
        cursor = state["cursor"]
        # Finished runs are immutable; an explicit new invocation takes a new snapshot.
        if force_new or not cursor or cursor.get("phase") == "complete":
            expected = await self._count()
            cursor = {"snapshot_id": uuid4().hex, "started_at": datetime.now(UTC).isoformat(),
                      "expected_count": expected, "page_size": self.page_size, "node": "hs_a",
                      "next_page": 1, "collected": 0, "last_symbol": "", "phase": "pages"}
            pages = (expected + self.page_size - 1) // self.page_size
            self.queue_reservation = await self.ingest.reserve_batch(self.job_key, pages + 2)
            state = await self._publish("stock.universe.start", state, cursor,
                                        {"count_before": expected}, "start")
        elif self.queue_reservation is None:
            pages = (cursor["expected_count"] + cursor["page_size"] - 1) // cursor["page_size"]
            remaining = ((pages - cursor["next_page"] + 1)
                         if cursor.get("phase") == "pages" else 0) + 1
            self.queue_reservation = await self.ingest.reserve_batch(self.job_key, remaining)
        if cursor.get("node") != "hs_a" or cursor.get("page_size") != self.page_size:
            raise ValueError("采集配置与断点不一致，请使用“重新采集”创建新批次")
        if cursor["phase"] == "pages":
            state = await self.collect_pages(state, DATA_URL)
            cursor = state["cursor"]
        if cursor["phase"] == "verify":
            terminal = await self._page(cursor["next_page"], cursor["page_size"])
            if terminal:
                raise ValueError("采集尾页不为空，请重新采集；已有完整列表不变")
            after = await self._count()
            if after != cursor["expected_count"]:
                raise ValueError("采集期间股票总数变化或尾页不为空，请重新采集；已有完整列表不变")
            updated = {**cursor, "phase": "complete"}
            await self._publish("stock.universe.complete", state, updated, {
                "collected": cursor["collected"], "count_after": after,
                "pages": cursor["next_page"] - 1, "terminal_rows": terminal,
            }, "complete")
            cursor = updated
        return {"snapshot_id": cursor["snapshot_id"], "collected": cursor["collected"],
                "expected_count": cursor["expected_count"], "pages": cursor["next_page"] - 1}

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
