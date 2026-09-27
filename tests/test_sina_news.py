import copy
from types import SimpleNamespace

import httpx
import pytest

from empire.contracts.download import NEWS_RESPONSE
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.collectors.sina_news import API_URL, SinaNewsCollector, parse_feed
from empire.plugins.datasets.astock import DatasetPlugin
from empire.plugins.datasets.news import normalize_source


def raw_row(ident, content="【市场快讯】黄金 &amp; 外汇<br>第二行", **extra):
    return {"id": ident, "rich_text": content, "create_time": "2026-09-23 08:01:02",
            "update_time": "2026-09-23 08:02:02", "tag": [{"id": "9", "name": "焦点"}],
            "is_focus": 1, "docurl": "https://finance.sina.com.cn/7x24/", "creator": "not-stored", **extra}


def response(ids, **extra):
    rows = [raw_row(ident, **extra) for ident in ids]
    return httpx.Response(200, request=httpx.Request("GET", API_URL), json={"result": {
        "status": {"code": 0}, "data": {"feed": {"list": rows, "min_id": min(ids) if ids else 0,
                                                "max_id": max(ids) if ids else 0}}}})


class MemoryIngest:
    def __init__(self):
        self.state = {"revision": 0, "cursor": {}}
        self.events = []

    async def checkpoint(self, job):
        return copy.deepcopy(self.state)

    async def ensure_capacity(self, incoming=1, reservation=None):
        pass

    async def publish_page(self, events, *, job_key, expected_revision, cursor, reservation=None):
        for event in events:
            DatasetPlugin().normalize(event)
        self.events.extend(events)
        return await self.advance_checkpoint(job_key=job_key, expected_revision=expected_revision, cursor=cursor)

    async def advance_checkpoint(self, *, job_key, expected_revision, cursor):
        assert self.state["revision"] == expected_revision
        self.state = {"revision": expected_revision + 1, "cursor": copy.deepcopy(cursor)}
        return copy.deepcopy(self.state)


class Diagnostics(RecordsPlugin):
    def __init__(self):
        super().__init__()
        self.errors = []

    async def add_error(self, project, **record):
        self.errors.append(record)


class Source:
    def response_policy(self, profile):
        assert profile == "news"
        return NEWS_RESPONSE

    def __init__(self, pages):
        self.pages = pages
        self.calls = []

    async def request(self, method, url, *, params, **kwargs):
        assert kwargs["project_id"] == "sina-news"
        assert params["page"] == 1 and params["tag"] == 0 and params["size"] == 50
        before = params.get("id", 0)
        self.calls.append(before)
        value = self.pages[before]
        if isinstance(value, Exception):
            raise value
        return value


def collector(pages):
    item = SinaNewsCollector()
    item.http, item.ingest, item.records = Source(pages), MemoryIngest(), Diagnostics()

    async def archived(source, job_key, project_id, batch, page):
        assert source == "sina" and job_key == "sina-news-v1"
        assert project_id == "sina-news"
        return {"status": "complete", "page": page}

    item.confirmation = SimpleNamespace(page_status=archived)
    return item


def test_normalizes_only_business_fields_and_china_time():
    row = normalize_source(raw_row(99))
    assert row["title"] == "市场快讯"
    assert row["content"] == "【市场快讯】黄金 & 外汇\n第二行"
    assert row["published_at"] == "2026-09-23T00:01:02+00:00"
    assert row["is_important"]
    assert "creator" not in row
    assert "evil" not in normalize_source(raw_row(99, "<script>evil()</script>新闻"))["content"]


@pytest.mark.parametrize("changes", [{"id": True}, {"rich_text": ""}, {"create_time": "invalid"},
                                      {"docurl": "javascript:alert(1)"}, {"tag": "wrong"}])
def test_invalid_news_is_rejected(changes):
    with pytest.raises((ValueError, TypeError)):
        normalize_source({**raw_row(1), **changes})


def test_pagination_rejects_repeat_boundary_and_duplicate_ids():
    with pytest.raises(ValueError):
        parse_feed(response([101, 100]), before_id=100)
    with pytest.raises(ValueError):
        parse_feed(response([101, 101]))


async def test_seed_then_incremental_catches_up_without_moving_page_offsets():
    item = collector({0: response([100, 99])})
    assert (await item.execute())["high_watermark"] == 100
    baseline = await item.checkpoint_revision()
    item.http = Source({0: response([103, 102]), 102: response([101, 100])})
    result = await item.execute(baseline_revision=baseline)
    assert result["collected"] == 4
    assert result["high_watermark"] == 103
    assert item.http.calls == [0, 102]
    assert len(item.ingest.events) == 3
    assert all("rich_text" not in e.raw_payload and "creator" not in str(e.raw_payload) for e in item.ingest.events)


async def test_interruption_resumes_before_id_and_does_not_skip_unarchived_watermark():
    item = collector({0: response([100, 99])})
    await item.execute()
    baseline = await item.checkpoint_revision()
    item.http = Source({0: response([103, 102]), 102: ConnectionError("offline")})
    with pytest.raises(ConnectionError):
        await item.execute(baseline_revision=baseline)
    checkpoint = item.ingest.state["cursor"]
    assert checkpoint["before_id"] == 102 and checkpoint["high_watermark"] == 100
    item.http = Source({102: response([101, 100])})
    await item.execute(baseline_revision=baseline)
    assert item.http.calls == [102]
    assert item.ingest.state["cursor"]["high_watermark"] == 103


async def test_source_gap_is_reported_without_advancing_high_watermark():
    item = collector({0: response([100])})
    await item.execute()
    baseline = await item.checkpoint_revision()
    item.http = Source({0: response([105, 104]), 104: response([])})
    with pytest.raises(ValueError, match="缺口未跳过"):
        await item.execute(baseline_revision=baseline)
    assert item.ingest.state["cursor"]["high_watermark"] == 100
    assert item.records.errors[-1]["stage"] == "coverage"
    # Explicit fresh restarts the recent baseline but does not issue any SQL deletion.
    item.http = Source({0: response([105, 104])})
    result = await item.execute(fresh=True, baseline_revision=await item.checkpoint_revision())
    assert result["high_watermark"] == 105


async def test_invalid_response_keeps_raw_diagnostic_without_publishing():
    bad = httpx.Response(200, request=httpx.Request("GET", API_URL), content=b"<html>maintenance</html>")
    item = collector({0: bad})
    with pytest.raises(ValueError):
        await item.execute()
    assert item.ingest.state["revision"] == 0
    assert not item.ingest.events
    assert item.records.errors[0]["raw_body"] == bad.content


async def test_empty_initial_feed_and_active_run_recovery_are_safe():
    item = collector({0: response([])})
    result = await item.execute()
    assert result["collected"] == 0
    previous_calls = len(item.http.calls)
    assert await item.execute(baseline_revision=0) == result
    assert len(item.http.calls) == previous_calls


async def test_first_run_is_one_full_page_and_overlap_stops_immediately():
    item = collector({0: response(list(range(100, 50, -1)))})
    result = await item.execute()
    assert result["collected"] == 50 and result["pages"] == 1
    assert item.http.calls == [0]
    item.http = Source({0: response(list(range(105, 55, -1)))})
    await item.execute(baseline_revision=await item.checkpoint_revision())
    assert item.http.calls == [0]
    assert item.ingest.state["cursor"]["high_watermark"] == 105


async def test_old_refresh_pages_checkpoint_does_not_force_extra_pages():
    item = collector({200: response([199, 100, 99])})
    item.ingest.state = {"revision": 1, "cursor": {
        "batch_id": "old-run", "phase": "fetch", "before_id": 200,
        "high_watermark": 100, "upper_id": 210, "pages": 1, "collected": 20,
        "covered": False, "refresh_pages": 5,
    }}
    result = await item.execute(baseline_revision=1)
    assert result["pages"] == 2 and item.http.calls == [200]
