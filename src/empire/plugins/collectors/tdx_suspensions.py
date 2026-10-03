"""TDX suspension history: complete calendar dates grouped into archive periods."""
import asyncio
import json
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from uuid import uuid4

from empire.contracts.collection_integrity import confirmed_distinct_records, require_complete_set
from empire.contracts.collector import SuspensionRunResult
from empire.contracts.plugin import PluginManifest
from empire.core.time import CHINA
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)
from empire.plugins.collectors.suspension_batches import bounded_batches
from empire.plugins.data.suspensions import periods_between
from empire.plugins.datasets.suspensions import (
    event_identity,
    normalize_source_row,
    source_security,
)

API_URL = "http://page2.tdx.com.cn:7615/TQLEX?Entry=CWServ.tdxsj_tzrl_gsrl"
PAGE_URL = "http://page2.tdx.com.cn:7615/site/tdxsj/html/tdxsj_tzrl_tzrl.html"
PAGE_SIZE = 1000
MAX_DAY_ROWS = 10000


def _result_set(value, index, columns):
    sets = value.get("ResultSets")
    if value.get("ErrorCode") != 0 or not isinstance(sets, list) or len(sets) <= index:
        raise ValueError("通达信停复牌响应缺少结果集")
    item = sets[index]
    if not isinstance(item, dict) or item.get("ColName") != columns or not isinstance(item.get("Content"), list):
        raise ValueError("通达信停复牌结果集结构无效")
    if item.get("Count") != len(item["Content"]):
        raise ValueError("通达信停复牌结果集条数不一致")
    return item["Content"]


def parse_page(response, requested_date, requested_page, *, initial):
    try:
        body = response.json()
    except (ValueError, UnicodeDecodeError):
        raise ValueError("通达信停复牌响应不是有效 JSON") from None
    rows = _result_set(body, 0, ["sc", "code", "name", "fprq", "sj", "sjcontent", "tprq"])
    metadata = _result_set(body, 1, ["page", "sflag", "sdate", "stype"])
    if metadata != [[requested_page, "mrtbts", requested_date, "hstfp"]]:
        raise ValueError("通达信停复牌响应日期、类型或页码不匹配")
    total = None
    if initial:
        totals = _result_set(body, 2, ["count"])
        if len(totals) != 1 or len(totals[0]) != 1 or type(totals[0][0]) is not int or totals[0][0] < 0:
            raise ValueError("通达信停复牌 A 股总数无效")
        total = totals[0][0]
    mapped = []
    for values in rows:
        if not isinstance(values, list) or len(values) != 7:
            raise ValueError("通达信停复牌记录列数无效")
        mapped.append(dict(zip(
            ("sc", "code", "name", "fprq", "sj", "sjcontent", "tprq"), values, strict=True)))
    return mapped, total


def merge_event(existing, incoming):
    if existing == incoming:
        return existing
    raise ValueError(f"同一停复牌来源记录内容冲突：{event_identity(existing)}")


class TdxSuspensionCollector:
    manifest = PluginManifest(
        "collector.tdx_suspensions", "通达信沪深 A 股历史停复牌",
        requires=("http.fetch", "ingest.publish", "suspensions.query",
                  "archive.confirmation", "collection.records"),
        provides=("collector.tdx_suspensions",),
        description="首次按自然月补齐 2004-12-27 至今；后续重查最后覆盖日并补采新增日期",
    )

    def __init__(self, today=None):
        self.today = today or (lambda: datetime.now(CHINA).date())
        self.source, self.project_id, self.job_key = "tdx", "tdx-suspensions", "tdx-suspensions-v1"
        self.http = self.ingest = self.query = self.confirmation = self.records = None
        self.request_retries = 2
        self.stats = {"status": "stopped", "collected": 0}

    async def start(self, context):
        self.http, self.ingest = context.get("http.fetch"), context.get("ingest.publish")
        self.query = context.get("suspensions.query")
        self.confirmation = context.get("archive.confirmation")
        self.records = context.get("collection.records")
        self.stats["status"] = "idle"
        return {"collector.tdx_suspensions": self}

    async def checkpoint_revision(self):
        return (await self.ingest.checkpoint(self.job_key))["revision"]

    async def _request_page(self, day, page, *, page_size=PAGE_SIZE):
        initial = page == 1
        body = json.dumps({"Params": ["mrtbts", "hstfp", day, "1" if initial else "0",
                                            str(page), str(page_size)]}, separators=(",", ":"))
        response = await self.http.request(
            "POST", API_URL, content=body.encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "Origin": "http://page2.tdx.com.cn:7615", "Referer": PAGE_URL},
            allowed_domains=("tdx.com.cn",), project_id=self.project_id,
            policy=self.http.response_policy("generic"), max_retries=self.request_retries,
        )
        try:
            return parse_page(response, day, page, initial=initial)
        finally:
            response.close()

    async def _collect_day(self, day):
        size, requests = PAGE_SIZE, 0
        while True:
            await wait_for_capacity(self.ingest, self.stats)
            source_rows, reported = (await self._request_page(day, 1) if size == PAGE_SIZE
                                     else await self._request_page(day, 1, page_size=size))
            requests += 1
            # TDX orders only by security; different events for the same code
            # swap across offset-page boundaries. Always replace the entire day.
            if len(source_rows) < size:
                break
            if size == MAX_DAY_ROWS:
                raise ValueError('通达信停复牌单日集合超出安全上限；不发布不完整日期')
            size = min(MAX_DAY_ROWS, size * 2)
        normalized, source_a_shares = [], []
        for row in source_rows:
            _, is_a_share = source_security(row)
            value = normalize_source_row(row)
            if is_a_share:
                source_a_shares.append(row)
            if value is not None:
                normalized.append(value)
        def identity(row):
            return json.dumps([row[k] for k in ('sc', 'code', 'tprq', 'fprq', 'sj', 'sjcontent')])
        if len(source_a_shares) != reported:
            raise ValueError(f'通达信停复牌 {day} 来源报告 {reported} 条，分页取得 {len(source_a_shares)} 条')
        if len({identity(row) for row in source_a_shares}) != len(source_a_shares):
            await wait_for_capacity(self.ingest, self.stats)
            verify_size = min(MAX_DAY_ROWS, size * 2)
            repeated, total = await self._request_page(day, 1, page_size=verify_size)
            requests += 1
            if total != reported or len(repeated) >= verify_size:
                raise ValueError('来源业务键重复且完整响应复核不一致')
            source_a_shares = confirmed_distinct_records(
                source_a_shares, [row for row in repeated if source_security(row)[1]], identity)
            normalized = [value for row in source_a_shares
                          if (value := normalize_source_row(row)) is not None]
        require_complete_set(source_a_shares, len(source_a_shares), identity)
        require_complete_set(normalized, len(normalized), event_identity)
        return normalized, requests

    async def execute(self, *, fresh=False, baseline_revision=0) -> SuspensionRunResult:
        stage, current_date, current_period = "checkpoint", None, None
        try:
            state = await self.ingest.checkpoint(self.job_key)
            cursor = state["cursor"]
            progressed = state["revision"] > baseline_revision
            if progressed and cursor.get("phase") == "complete":
                return self._result(cursor)
            if not cursor or (fresh and not progressed) or cursor.get("phase") == "complete":
                plan = await self.query.plan(self.today(), fresh=fresh)
                cursor = {**{key: value for key, value in plan.items() if key != "periods"},
                          "batch_id": uuid4().hex, "phase": "fetch", "period_index": 0,
                          "pages": 0, "collected": 0, "dates_checked": 0,
                          "started_at": datetime.now(UTC).isoformat()}
            periods = periods_between(datetime.fromisoformat(cursor["start_date"]).date(),
                                      datetime.fromisoformat(cursor["end_date"]).date())
            while cursor["phase"] == "fetch":
                current_period = periods[cursor["period_index"]]
                start = datetime.fromisoformat(current_period["start_date"]).date()
                if cursor.get('resume_date'):
                    start = max(start, datetime.fromisoformat(cursor['resume_date']).date())
                end = datetime.fromisoformat(current_period["end_date"]).date()
                days = []
                day = start
                while day <= end:
                    current_date = day.isoformat()
                    self.stats.update(status="collecting", current_date=current_date,
                        current_month=current_period["period"], collected=cursor["collected"],
                        pages=cursor["pages"], total_months=len(periods), error="")
                    stage = "http_request"
                    rows, pages = await self._collect_day(current_date)
                    stage = "suspension_validation"
                    days.append((current_date, rows, pages))
                    day += timedelta(days=1)
                batches = bounded_batches(
                    days, source=self.source, job_key=self.job_key, batch_id=cursor['batch_id'],
                    first_page=cursor['pages'] + 1, source_url=API_URL, merge=merge_event,
                    limit=getattr(self.ingest, 'settings', {}).get('max_page_bytes', 524288),
                )
                for event, count, day_count, source_pages in batches:
                    last = datetime.fromisoformat(event.raw_payload['end_date']).date()
                    next_index = cursor['period_index'] + int(last == end)
                    updated = {**cursor, 'period_index': next_index, 'pages': cursor['pages'] + 1,
                               'resume_date': (last + timedelta(days=1)).isoformat(),
                               'collected': cursor['collected'] + count,
                               'dates_checked': cursor['dates_checked'] + day_count,
                               'source_pages': cursor.get('source_pages', 0) + source_pages,
                               'phase': 'awaiting_archive' if next_index == len(periods) else 'fetch'}
                    stage = 'queue_publish'
                    state = await publish_with_capacity(
                        self.ingest, self.stats, [event], job_key=self.job_key,
                        expected_revision=state['revision'], cursor=updated,
                    )
                    cursor = state['cursor']
            stage = "archive_confirmation"
            self.stats.update(status="awaiting_archive", collected=cursor["collected"], pages=cursor["pages"])
            await self._confirm(cursor)
            cursor = {**cursor, "phase": "complete"}
            await self.ingest.advance_checkpoint(
                job_key=self.job_key, expected_revision=state["revision"], cursor=cursor)
            self.stats.update(status="complete", error="")
            return self._result(cursor)
        except asyncio.CancelledError:
            self.stats["status"] = "paused"
            raise
        except Exception as exc:
            self.stats.update(status="error", error=self.records.sanitize_text(exc))
            await record_error_safely(
                self.records, self.stats, self.project_id, exc, stage=stage,
                unavailable_message="错误记录暂未写入 Redis；断点保留",
                fields={"request_url": API_URL,
                        "metadata": {"date": current_date, "period": current_period}},
            )
            raise

    @staticmethod
    def _result(cursor: dict[str, Any]) -> SuspensionRunResult:
        return {"collected": cursor["collected"], "pages": cursor["pages"],
                "source_pages": cursor.get("source_pages", 0), "dates_checked": cursor["dates_checked"],
                "batch_id": cursor["batch_id"], "start_date": cursor["start_date"],
                "end_date": cursor["end_date"]}

    async def _confirm(self, cursor):
        self.stats.update(status="awaiting_archive", collected=cursor["collected"], pages=cursor["pages"])
        await wait_for_archive(partial(
            self.confirmation.page_status, self.source, self.job_key, self.project_id,
            cursor["batch_id"], cursor["pages"],
        ), retry_seconds=1)

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
