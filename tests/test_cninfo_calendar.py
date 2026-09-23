import copy
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.plugins.collectors.cninfo_calendar import API_URL, CninfoCalendarCollector, parse_month
from empire.plugins.data.trade_calendar import CalendarDataPlugin
from empire.plugins.datasets.astock import DatasetPlugin
from empire.plugins.datasets.trade_calendar import month_dates, months_between


def response(month):
    return httpx.Response(200, request=httpx.Request("GET", API_URL), json={"monthTradeDate": [
        {"tradeDate": day.isoformat(), "isTrade": str(int(day.weekday() < 5)),
         "week": str((day.weekday() + 1) % 7)} for day in month_dates(month)], "currentDate": "2026-09-23"})


def test_source_start_and_leap_month_are_complete():
    assert len(parse_month(response("1990-12"), "1990-12")) == 13
    assert len(parse_month(response("2024-02"), "2024-02")) == 29
    assert parse_month(response("1990-12"), "1990-12")[0]["trade_date"] == "1990-12-19"


@pytest.mark.parametrize("issue", ["empty", "missing", "duplicate", "wrong_month", "week", "flag"])
def test_invalid_month_is_not_treated_as_nontrading(issue):
    body = response("2026-09").json()
    rows = body["monthTradeDate"]
    if issue == "empty":
        rows.clear()
    elif issue == "missing":
        rows.pop()
    elif issue == "duplicate":
        rows[-1] = rows[0]
    elif issue == "wrong_month":
        rows[0]["tradeDate"] = "2026-10-01"
    elif issue == "week":
        rows[0]["week"] = "99"
    else:
        rows[0]["isTrade"] = "unknown"
    with pytest.raises(ValueError):
        parse_month(httpx.Response(200, json=body), "2026-09")


async def test_plan_full_history_then_maintenance_and_missing_history_after_redis_loss():
    query = CalendarDataPlugin()
    query.mysql = SimpleNamespace(read=AsyncMock(return_value={}))
    initial = await query.plan(date(2026, 9, 23))
    assert len(initial["months"]) == 445
    assert initial["months"][0] == "1990-12" and initial["months"][-1] == "2027-12"
    coverage = {month: len(month_dates(month)) for month in initial["months"]}
    query.mysql.read.return_value = coverage
    maintenance = await query.plan(date(2026, 9, 23))
    assert maintenance["months"] == months_between("2026-09", "2027-12")
    assert maintenance["expected_count"] == 487
    coverage["2000-02"] -= 1
    missing = await query.plan(date(2026, 9, 23))
    assert missing["months"] == ["2000-02", *maintenance["months"]]
    new_year = await query.plan(date(2027, 1, 1))
    assert new_year["months"][-1] == "2028-12"
    assert (await query.plan(date(2026, 9, 23), fresh=True))["months"] == initial["months"]


class MemoryIngest:
    def __init__(self):
        self.state = {"revision": 0, "cursor": {}}
        self.events = []

    async def checkpoint(self, job):
        return copy.deepcopy(self.state)

    async def ensure_capacity(self):
        pass

    async def publish_page(self, events, *, job_key, expected_revision, cursor):
        for event in events:
            DatasetPlugin().normalize(event)
        self.events.extend(events)
        return await self.advance_checkpoint(job_key=job_key, expected_revision=expected_revision, cursor=cursor)

    async def advance_checkpoint(self, *, job_key, expected_revision, cursor):
        assert self.state["revision"] == expected_revision
        self.state = {"revision": expected_revision + 1, "cursor": copy.deepcopy(cursor)}
        return copy.deepcopy(self.state)


def collector():
    item = CninfoCalendarCollector(today=lambda: date(2026, 9, 23))
    item.ingest = MemoryIngest()
    item.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    item.query = SimpleNamespace(
        plan=AsyncMock(return_value={"months": ["2026-09", "2026-10"], "maintenance_start": "2026-09",
                                    "end_month": "2027-12", "expected_count": 61}),
        page_status=AsyncMock(return_value={"status": "complete"}))
    async def get(method, url, **kwargs):
        assert url == API_URL and kwargs["project_id"] == "cninfo-calendar"
        assert kwargs["allowed_domains"] == ("cninfo.com.cn",)
        return response(kwargs["params"]["month"])
    item.http = SimpleNamespace(request=AsyncMock(side_effect=get))
    return item


async def test_collects_months_and_finishes_only_after_archive_confirmation():
    item = collector()
    result = await item.execute()
    assert result["collected"] == 61 and result["pages"] == 2
    assert [call.kwargs["params"]["month"] for call in item.http.request.call_args_list] == ["2026-09", "2026-10"]
    item.query.page_status.assert_awaited()
    assert item.ingest.state["cursor"]["phase"] == "complete"
    assert await item.execute(baseline_revision=0) == result
    assert item.http.request.await_count == 2


async def test_month_failure_keeps_progress_and_resumes_exact_failed_month():
    item = collector()
    item.http.request.side_effect = [response("2026-09"), httpx.Response(
        200, request=httpx.Request("GET", API_URL), json={"monthTradeDate": []})]
    with pytest.raises(ValueError, match="为空"):
        await item.execute()
    assert item.ingest.state["cursor"]["pages"] == 1
    assert len(item.ingest.events) == 1
    assert item.records.add_error.call_args.kwargs["metadata"] == {"month": "2026-10"}
    item.http.request.side_effect = [response("2026-10")]
    await item.execute(baseline_revision=0)
    assert item.http.request.call_args.kwargs["params"] == {"month": "2026-10"}
    assert item.query.plan.await_count == 1


async def test_invalid_archive_does_not_mark_run_complete():
    item = collector()
    item.query.page_status.return_value = {"status": "invalid", "error_text": "invalid page"}
    with pytest.raises(ValueError, match="invalid page"):
        await item.execute()
    assert item.ingest.state["cursor"]["phase"] == "awaiting_archive"
