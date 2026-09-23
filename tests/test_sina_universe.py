import asyncio
import copy
import json
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest

from empire.contracts.data import make_envelope
from empire.contracts.stocks import normalize_sina_stock
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.collectors.sina_universe import SinaUniverseCollector, decode_json, parse_count
from empire.plugins.datasets.astock import DatasetPlugin


def row(symbol, name="测试股票"):
    return {"symbol": symbol, "code": symbol[2:], "name": name}


@pytest.mark.parametrize("symbol,unified,market", [
    ("sz000001", "000001.SZ", "SZ"), ("sh600519", "600519.SH", "SH"),
    ("bj920000", "920000.BJ", "BJ"),
])
def test_identifiers_are_source_independent_and_keep_leading_zero(symbol, unified, market):
    result = normalize_sina_stock(row(symbol))
    assert result["code"] == symbol[2:]
    assert result["unified_code"] == unified
    assert result["market"] == market


@pytest.mark.parametrize("data", [
    {"symbol": "sz000001", "code": 1, "name": "平安银行"},
    {"symbol": "sh600000", "code": "000001", "name": "不一致"},
    row("hk000001"), row("sz000001", ""),
])
def test_invalid_identities_are_not_guessed(data):
    with pytest.raises(ValueError):
        normalize_sina_stock(data)


def test_gbk_response_keeps_chinese_names():
    response = httpx.Response(200, headers={"Content-Type": "application/json; charset=gbk"},
                              content=json.dumps([row("sz000001", "平安银行")], ensure_ascii=False).encode("gbk"))
    assert decode_json(response)[0]["name"] == "平安银行"


@pytest.mark.parametrize("count", [0, "0", None, True, {"error": "busy"}])
def test_empty_or_error_count_cannot_publish_empty_market(count):
    with pytest.raises(ValueError):
        parse_count(count)


class MemoryIngest:
    def __init__(self):
        self.state = {"revision": 0, "cursor": {}}
        self.events = []

    async def checkpoint(self, key):
        return copy.deepcopy(self.state)

    async def ensure_capacity(self):
        pass

    async def publish_page(self, envelopes, *, job_key, expected_revision, cursor):
        assert expected_revision == self.state["revision"]
        for event in envelopes:
            DatasetPlugin().normalize(event)
        self.events.extend(envelopes)
        self.state = {"revision": expected_revision + 1, "cursor": copy.deepcopy(cursor)}
        return copy.deepcopy(self.state)


class Source:
    def __init__(self, pages, count=3, count_after=None, fail_page=None):
        self.pages, self.count, self.count_after = pages, count, count_after
        self.count_calls = 0
        self.fail_page = fail_page
        self.requested = []

    async def request(self, method, url, *, params, **kwargs):
        if "getHQNodeStockCount" in url:
            self.count_calls += 1
            data = str(self.count_after if self.count_calls > 1 and self.count_after is not None else self.count)
        else:
            assert params["sort"] == "symbol" and params["asc"] == 0
            assert params["node"] == "hs_a"
            page = params["page"]
            self.requested.append(page)
            if page == self.fail_page:
                raise ConnectionError("Injected interruption")
            data = self.pages.get(page, [])
        return httpx.Response(200, headers={"Content-Type": "application/json; charset=gbk"},
                              content=json.dumps(data, ensure_ascii=False).encode("gbk"))


class Diagnostics:
    def __init__(self):
        self.errors = []

    async def add_error(self, project_id, **record):
        self.errors.append({"project_id": project_id, **record})


def collector(source, ingest=None):
    result = SinaUniverseCollector({"page_size": 2})
    result.http = source
    result.ingest = ingest or MemoryIngest()
    result.records = Diagnostics()
    return result


async def test_collects_all_pages_and_persists_completion_evidence():
    source = Source({1: [row("sz000001"), row("sh600519")], 2: [row("bj920000")]})
    item = collector(source)
    result = await item._collect()
    assert result["collected"] == 3
    assert source.requested == [1, 2, 3]
    assert [e.dataset for e in item.ingest.events] == [
        "stock.universe.start", "stock.universe.page", "stock.universe.page", "stock.universe.complete",
    ]
    assert item.ingest.state["cursor"]["phase"] == "complete"
    assert item.records.errors == []
    assert item._response is None


async def test_resume_starts_at_uncommitted_page_not_page_one():
    pages = {1: [row("sz000001"), row("sh600519")], 2: [row("bj920000")]}
    first = collector(Source(pages, fail_page=2))
    with pytest.raises(ConnectionError):
        await first._collect()
    assert first.ingest.state["cursor"]["next_page"] == 2
    second = collector(Source(pages), first.ingest)
    result = await second._collect()
    assert second.http.requested == [2, 3]
    assert result["collected"] == 3
    assert len([e for e in first.ingest.events if e.dataset.endswith("page")]) == 2


async def test_control_recovery_after_enqueue_does_not_create_a_second_snapshot():
    source = Source({1: [row("sz000001"), row("sh600519")], 2: [row("bj920000")]})
    item = collector(source)
    result = await item._collect()
    before = len(item.ingest.events)

    class Query:
        async def batch_status(self, snapshot_id):
            assert snapshot_id == result["snapshot_id"]
            return {"status": "complete"}

    item.query = Query()
    recovered = await item.execute(fresh=True, baseline_revision=0)
    assert recovered["snapshot_id"] == result["snapshot_id"]
    assert len(item.ingest.events) == before
    assert item.health()["status"] == "complete"


@pytest.mark.parametrize("pages,count_after", [
    ({1: [row("sz000001"), row("sh600519")], 2: []}, None),
    ({1: [row("sz000001"), row("sh600519")], 2: [row("sh600519")]}, None),
    ({1: [row("sz000001"), row("sh600519")], 2: [row("bj920000")]}, 4),
    ({1: [row("sz000001"), row("sh600519")], 2: [row("bj920000")], 3: [row("bj830001")]}, None),
])
async def test_incomplete_or_moving_universe_is_never_completed(pages, count_after):
    item = collector(Source(pages, count_after=count_after))
    with pytest.raises(ValueError):
        await item._collect()
    assert not any(e.dataset.endswith("complete") for e in item.ingest.events)
    assert item.ingest.state["cursor"]["phase"] != "complete"


def test_page_contract_rejects_duplicate_symbols():
    snapshot = uuid4().hex
    event = make_envelope(
        source="sina", dataset="stock.universe.page", business_key=f"{snapshot}:page:1",
        job_key="test", run_id=snapshot, batch_id=snapshot,
        payload={"snapshot_id": snapshot, "started_at": datetime.now(UTC).isoformat(),
                 "expected_count": 2, "page_size": 2, "node": "hs_a", "page": 1,
                 "rows": [row("sz000001"), row("sz000001")]},
    )
    with pytest.raises(ValueError, match="duplicated"):
        DatasetPlugin().normalize(event)


async def test_successful_response_fields_are_discarded_before_enqueue():
    supplied = {**row("sz000001"), "price": "12.34", "arbitrary": "should not survive"}
    item = collector(Source({1: [supplied, row("sh600519")], 2: [row("bj920000")]}))
    await item._collect()
    rows = [event.raw_payload["rows"] for event in item.ingest.events if event.dataset.endswith("page")]
    assert set(rows[0][0]) == {"code", "name", "unified_code", "market", "source_symbol"}
    assert "should not survive" not in json.dumps([event.raw_payload for event in item.ingest.events])


async def test_invalid_page_captures_the_original_failed_response_and_stage():
    item = collector(Source({1: [row("sz000001")]}))
    with pytest.raises(ValueError):
        await item._collect()
    assert len(item.records.errors) == 1
    error = item.records.errors[0]
    assert error["project_id"] == "sina-stocks"
    assert error["stage"] == "page_validation"
    assert b"sz000001" in error["raw_body"]
    assert error["status_code"] == 200
    assert error["metadata"]["params"]["page"] == 1
    assert item._response is None


async def test_http_error_keeps_response_while_network_error_has_only_request_metadata():
    class FailingSource:
        async def request(self, method, url, **kwargs):
            response = httpx.Response(503, content=b"upstream unavailable", request=httpx.Request(method, url))
            response.raise_for_status()

    item = collector(FailingSource())
    with pytest.raises(httpx.HTTPStatusError):
        await item._collect()
    assert item.records.errors[0]["status_code"] == 503
    assert item.records.errors[0]["raw_body"] == b"upstream unavailable"
    network = collector(Source({}, fail_page=1))
    with pytest.raises(ConnectionError):
        await network._collect()
    assert "raw_body" not in network.records.errors[0]
    assert "page=1" in network.records.errors[0]["request_url"]


async def test_invalid_json_count_and_sort_errors_are_recorded_without_checkpoint_advance():
    class BadJson:
        async def request(self, *args, **kwargs):
            return httpx.Response(200, content=b"<html>temporarily blocked</html>")

    item = collector(BadJson())
    with pytest.raises(ValueError):
        await item._collect()
    assert item.records.errors[0]["stage"] == "json_decode"
    assert item.ingest.state["revision"] == 0

    item = collector(Source({}, count=0))
    with pytest.raises(ValueError):
        await item._collect()
    assert item.records.errors[0]["stage"] == "count_validation"
    assert item.ingest.state["revision"] == 0

    item = collector(Source({1: [row("sh600519"), row("sz000001")]}))
    with pytest.raises(ValueError):
        await item._collect()
    assert item.records.errors[0]["stage"] == "stock_validation"
    assert item.ingest.state["cursor"]["next_page"] == 1


async def test_cancel_is_not_an_error_and_clears_transient_response():
    class CancelledSource:
        async def request(self, *args, **kwargs):
            raise asyncio.CancelledError

    item = collector(CancelledSource())
    with pytest.raises(asyncio.CancelledError):
        await item._collect()
    assert item.records.errors == []
    assert item._response is None


async def test_redis_diagnostic_failure_does_not_mask_original_source_error():
    class BrokenDiagnostics:
        async def add_error(self, *args, **kwargs):
            raise RuntimeError("Redis unavailable")

    item = collector(Source({}, count=0))
    item.records = BrokenDiagnostics()
    with pytest.raises(ValueError, match="股票总数无效"):
        await item._collect()
    assert item.stats["diagnostic_error"]


async def test_http_layer_recorded_error_is_not_logged_twice_by_collector():
    class RecordedFailureSource:
        async def request(self, *args, **kwargs):
            assert kwargs["project_id"] == "sina-stocks"
            error = ConnectionError("Already diagnosed by HTTP plugin")
            error.diagnostic_recorded = True
            raise error

    item = collector(RecordedFailureSource())
    with pytest.raises(ConnectionError):
        await item._collect()
    assert item.records.errors == []


async def test_collector_health_redacts_error_url_without_changing_http_exception_response():
    class SourceFailure:
        async def request(self, *args, **kwargs):
            url = "https://example.com/list?token=hidden-credential"
            response = httpx.Response(503, content=b"failed-response", request=httpx.Request("GET", url))
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                exc.diagnostic_recorded = True
                raise

    item = collector(SourceFailure())
    item.records = RecordsPlugin()
    with pytest.raises(httpx.HTTPStatusError) as caught:
        await item.execute()
    assert caught.value.response.content == b"failed-response"
    assert "hidden-credential" not in item.health()["error"]
