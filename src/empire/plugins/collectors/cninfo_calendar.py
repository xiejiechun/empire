"""CNINFO A-share calendar: initial history, then current month to next December."""
import asyncio
from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

from empire.contracts.data import BackpressureError, make_envelope
from empire.contracts.plugin import PluginManifest
from empire.plugins.datasets.trade_calendar import validate_rows

API_URL = "https://www.cninfo.com.cn/data/tradeday/getMonthTradeDay"
CHINA = timezone(timedelta(hours=8))


def parse_month(response, month):
    body = response.json()
    if not isinstance(body, dict) or not isinstance(body.get("monthTradeDate"), list):
        raise ValueError("巨潮日历缺少 monthTradeDate")
    rows = []
    for item in body["monthTradeDate"]:
        if not isinstance(item, dict) or str(item.get("isTrade")) not in ("0", "1"):
            raise ValueError("巨潮交易日标记无效")
        day = datetime.strptime(item["tradeDate"], "%Y-%m-%d").date()
        if str(item.get("week")) != str((day.weekday() + 1) % 7):
            raise ValueError("巨潮日期与星期不一致")
        rows.append({"trade_date": day.isoformat(), "is_trade": str(item["isTrade"]) == "1"})
    return validate_rows(month, rows)


class CninfoCalendarCollector:
    manifest = PluginManifest("collector.cninfo_calendar", "巨潮 A 股交易日期",
        requires=("http.fetch", "ingest.publish", "calendar.query", "collection.records"),
        provides=("collector.cninfo_calendar",),
        description="首次补齐历史；每轮维护本月至下一自然年年底，并补齐历史缺月")

    def __init__(self, today=None):
        self.today = today or (lambda: datetime.now(CHINA).date())
        self.source, self.project_id, self.job_key = "cninfo", "cninfo-calendar", "cninfo-calendar-v1"
        self.http = self.ingest = self.query = self.records = None
        self.request_retries = 2
        self.stats = {"status": "stopped", "collected": 0}

    async def start(self, context):
        self.http, self.ingest = context.get("http.fetch"), context.get("ingest.publish")
        self.query, self.records = context.get("calendar.query"), context.get("collection.records")
        self.stats["status"] = "idle"
        return {"collector.cninfo_calendar": self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))["revision"]

    async def _capacity(self):
        while True:
            try:
                await self.ingest.ensure_capacity()
                return
            except BackpressureError as exc:
                self.stats.update(status="paused", error=str(exc))
                await asyncio.sleep(5)

    async def execute(self, *, fresh=False, baseline_revision=0):
        response = None
        stage = "checkpoint"
        month = None
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state["cursor"]
            progressed = state["revision"] > baseline_revision
            if progressed and cursor.get("phase") == "complete":
                return self._result(cursor)
            if not cursor or (fresh and not progressed) or cursor.get("phase") == "complete":
                plan = await self.query.plan(self.today(), fresh=fresh)
                cursor = {**plan, "batch_id": uuid4().hex, "phase": "fetch", "pages": 0,
                          "collected": 0, "started_at": datetime.now(UTC).isoformat()}
            while cursor["phase"] == "fetch":
                response = None
                month = cursor["months"][cursor["pages"]]
                self.stats.update(status="collecting", current_month=month, collected=cursor["collected"],
                                  expected_count=cursor["expected_count"], pages=cursor["pages"],
                                  total_months=len(cursor["months"]), error="")
                await self._capacity()
                stage = "http_request"
                response = await self.http.request("GET", API_URL, params={"month": month},
                    allowed_domains=("cninfo.com.cn",), project_id=self.project_id,
                    max_retries=self.request_retries)
                stage = "calendar_validation"
                rows = parse_month(response, month)
                page = cursor["pages"] + 1
                updated = {**cursor, "pages": page, "collected": cursor["collected"] + len(rows),
                           "phase": "awaiting_archive" if page == len(cursor["months"]) else "fetch"}
                event = make_envelope(source=self.source, dataset="calendar.month", job_key=self.job_key,
                    business_key=f"{cursor['batch_id']}:{month}", run_id=cursor["batch_id"], batch_id=cursor["batch_id"],
                    payload={"page": page, "month": month, "rows": rows}).model_copy(update={"source_url": API_URL})
                response = None
                stage = "queue_publish"
                while True:
                    try:
                        state = await self.ingest.publish_page([event], job_key=self.job_key,
                            expected_revision=state["revision"], cursor=updated)
                        break
                    except BackpressureError:
                        await self._capacity()
                cursor = state["cursor"]
            stage = "archive_confirmation"
            self.stats.update(status="awaiting_archive", collected=cursor["collected"],
                              pages=cursor["pages"], expected_count=cursor["expected_count"])
            while True:
                result = await self.query.page_status(cursor["batch_id"], cursor["pages"])
                if result and result["status"] == "invalid":
                    raise ValueError(result["error_text"])
                if result and result["status"] == "complete":
                    break
                await asyncio.sleep(1)
            cursor = {**cursor, "phase": "complete"}
            await self.ingest.advance_checkpoint(job_key=self.job_key, expected_revision=state["revision"], cursor=cursor)
            self.stats.update(status="complete", error="")
            return self._result(cursor)
        except asyncio.CancelledError:
            self.stats["status"] = "paused"
            raise
        except Exception as exc:
            self.stats.update(status="error", error=self.records.sanitize_text(exc))
            if not getattr(exc, "diagnostic_recorded", False):
                try:
                    await self.records.add_error(self.project_id, stage=stage, error=str(exc),
                        raw_body=response.content if response is not None else None,
                        request_url=str(response.url) if response is not None else API_URL,
                        status_code=response.status_code if response is not None else None,
                        metadata={"month": month})
                except Exception:
                    self.stats["diagnostic_error"] = "错误记录暂未写入 Redis；断点保留"
            raise

    def _result(self, cursor):
        return {"collected": cursor["collected"], "pages": cursor["pages"], "batch_id": cursor["batch_id"],
                "start_month": cursor["months"][0], "end_month": cursor["end_month"],
                "maintenance_start": cursor["maintenance_start"]}

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
