import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.margin.collector import MarginCollector
from tests.prefetch_source import prefetch_http
from tests.test_tdx_margin import response


def collector():
    c = MarginCollector()
    state, events = {"revision": 0, "cursor": {}}, []

    async def publish(envelopes, **kwargs):
        assert kwargs["expected_revision"] == state["revision"]
        state.update(revision=state["revision"] + 1, cursor=copy.deepcopy(kwargs["cursor"]))
        events.extend(envelopes)
        return copy.deepcopy(state)

    async def advance(**kwargs):
        state.update(revision=state["revision"] + 1, cursor=copy.deepcopy(kwargs["cursor"]))
        return copy.deepcopy(state)

    c.ingest = SimpleNamespace(
        checkpoint=AsyncMock(side_effect=lambda _: copy.deepcopy(state)),
        publish_page=AsyncMock(side_effect=publish),
        advance_checkpoint=AsyncMock(side_effect=advance),
        settings={"max_page_bytes": 524288},
        health=lambda: {},
        ensure_capacity=AsyncMock(),
    )
    c.query = SimpleNamespace(securities=AsyncMock(return_value=["600000.SH", "688256.SH"]))
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={"status": "complete"}))
    c.http = prefetch_http(
        request=AsyncMock(side_effect=lambda *a, **k: httpx.Response(200, json=response()))
    )
    return c, state, events


async def test_all_securities_publish_before_archive_wait_and_unchanged_cost(monkeypatch):
    c, state, events = collector()

    async def wait(*a, **kw):
        assert len(events) == c.http.request.call_count == 2

    monkeypatch.setattr("empire.features.margin.collector.wait_for_archive", wait)
    await c.execute()
    assert state["cursor"]["phase"] == "complete"
    assert len(json.dumps(state).encode()) < 1024
    events.clear()
    c.http.request.reset_mock()
    await c.execute(baseline_revision=state["revision"])
    assert all(
        json.loads(call.kwargs["content"])["Params"][-1] == "10000"
        for call in c.http.request.call_args_list
    )


async def test_failure_keeps_cursor_and_recovery_only_failed_security(monkeypatch):
    c, state, events = collector()

    def fetch(*a, **kw):
        code = json.loads(kw["content"])["Params"][2]
        return httpx.Response(200, json=response() if code == "600000" else {"ErrorCode": -1})

    c.http.request.side_effect = fetch
    monkeypatch.setattr("empire.features.margin.collector.wait_for_archive", AsyncMock())
    with pytest.raises(ValueError):
        await c.execute()
    assert state["cursor"]["index"] == 1 and len(events) == 1
    c.http.request.reset_mock()
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=response())
    await c.execute(baseline_revision=state["revision"])
    assert c.http.request.call_count == 1
    assert events[-1].raw_payload["code"] == "688256.SH"


async def test_redis_loss_refetches_explicit_whole_history_without_extra_requests(monkeypatch):
    c, state, events = collector()
    monkeypatch.setattr("empire.features.margin.collector.wait_for_archive", AsyncMock())
    await c.execute()
    state.update(revision=0, cursor={})
    c.http.request.reset_mock()
    await c.execute()
    assert c.http.request.call_count == 2


async def test_one_new_day_and_new_security_keep_one_request_per_complete_security(monkeypatch):
    c, state, events = collector()
    monkeypatch.setattr("empire.features.margin.collector.wait_for_archive", AsyncMock())
    await c.execute()
    body = response()
    body["ResultSets"][0]["Content"].insert(0, [100, 1000, 10, "20261029", 210, 20, 5, 1])
    body["ResultSets"][0]["Count"] = 3
    body["ResultSets"][2]["Content"] = [[3]]
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, json=body)
    c.http.request.reset_mock()
    events.clear()
    await c.execute(baseline_revision=state["revision"])
    assert c.http.request.call_count == len(events) == 2
    assert state["cursor"]["collected"] == 6
    c.query.securities.return_value.append("920001.BJ")
    c.http.request.reset_mock()
    events.clear()
    await c.execute(baseline_revision=state["revision"])
    assert c.http.request.call_count == len(events) == 3
    assert state["cursor"]["collected"] == 9
