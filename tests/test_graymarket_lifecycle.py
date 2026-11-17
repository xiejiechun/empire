import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.graymarket.codec import pack, unpack
from empire.features.graymarket.collector import GraymarketCollector
from tests.prefetch_source import prefetch_http
from tests.test_graymarket import DayAssembly, parsed, response


def collector():
    c = GraymarketCollector()
    state, published = dict(revision=0, cursor={}), []
    async def publish(envelopes, **kw):
        assert kw["expected_revision"] == state["revision"]
        published.extend(envelopes)
        state.update(revision=state["revision"] + 1, cursor=kw["cursor"])
        return copy.deepcopy(state)
    async def advance(**kw):
        state.update(revision=state["revision"] + 1, cursor=kw["cursor"])
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(side_effect=lambda _: copy.deepcopy(state)),
        ensure_capacity=AsyncMock(), publish_page=AsyncMock(side_effect=publish),
        advance_checkpoint=AsyncMock(side_effect=advance))
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.query = SimpleNamespace(trading_dates=AsyncMock(return_value=["2026-10-30", "2026-11-02"]),
                              covered=AsyncMock(return_value=set()))
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={"status": "complete"}))
    async def fetch(method, url, **kw):
        p = kw["params"]
        return httpx.Response(200, content=json.dumps(response(total=101, page=p["StartPage"],
            stamp=int(p["date"] or "20261102")), default=str).encode())
    c.http = prefetch_http(request=AsyncMock(side_effect=fetch))
    return c, state, published


async def test_publish_all_days_before_archive_and_reuse_discovery():
    c, state, published = collector()
    async def confirmed(*args):
        assert len(published) == 2
        assert c.http.request.call_count == 4  # 2 days * 2 pages, discovery reused
        assert published[0].observed_at == published[1].observed_at
        return {"status": "complete"}
    c.confirmation.page_status.side_effect = confirmed
    result = await c.execute(start="2026-10-30", end="2026-11-02")
    assert result["phase"] == "complete" and result["pages"] == 2
    assert all(len(unpack(e.raw_payload["rows"])) == 101 for e in published)
    assert len(json.dumps(state)) < 2048 and c.http.buffer_budget.used == 0


async def test_archive_failure_resumes_without_downloading(monkeypatch):
    c, state, published = collector()
    wait = AsyncMock(side_effect=RuntimeError("archive unavailable"))
    monkeypatch.setattr("empire.features.graymarket.collector.wait_for_archive", wait)
    with pytest.raises(RuntimeError, match="archive unavailable"):
        await c.execute(start="2026-10-30", end="2026-11-02")
    assert state["cursor"]["phase"] == "awaiting_archive"
    c.http.request.reset_mock()
    wait.side_effect = None
    await c.execute(start="2026-10-30", end="2026-11-02", baseline_revision=state["revision"])
    assert c.http.request.call_count == 0 and len(published) == 2


async def test_failure_does_not_publish_partial_day_or_download_later_days():
    c, state, published = collector()
    original = c.http.request.side_effect
    async def fail(*args, **kw):
        if kw["params"]["date"] == "20261030" and kw["params"]["StartPage"] == 2:
            return httpx.Response(200, json={"errid": -2})
        return await original(*args, **kw)
    c.http.request.side_effect = fail
    with pytest.raises(ValueError):
        await c.execute(start="2026-10-30", end="2026-11-02")
    assert not published and state["revision"] == 0
    assert c.http.buffer_budget.used == 0


def test_codec_rejects_truncation_size_and_extra_stream():
    import base64
    rows = DayAssembly(parsed(response(total=2))).finish()
    value = pack(rows)
    assert unpack(value) == rows
    for broken in ({**value, "size": 1}, {**value, "body": value["body"][:-3]},
                   {**value, "body": base64.b64encode(base64.b64decode(value["body"]) + b"tail").decode()}):
        with pytest.raises(ValueError):
            unpack(broken)
