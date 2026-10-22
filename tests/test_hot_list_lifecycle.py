"""No archive wait between dates; failed source cannot move the cursor."""

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.hot_list.collector import HotListCollector
from empire.features.hot_list.contract import CONTRACT
from tests.prefetch_source import prefetch_http
from tests.test_tdx_hot_list import CODE, DATE, detail, directory


def collector():
    c = HotListCollector()
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
    c.query = SimpleNamespace(
        securities=AsyncMock(return_value=[CODE]), day_heads=AsyncMock(return_value={})
    )
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={"status": "complete"}))
    import json

    c.http = prefetch_http(
        request=AsyncMock(
            side_effect=lambda *a, **k: httpx.Response(
                200,
                json=directory([DATE, "2009-12-25"])
                if json.loads(k["content"])["Params"][0] == "0"
                else detail(),
            )
        )
    )
    return c, state, events


async def test_publish_all_dates_before_waiting_archive(monkeypatch):
    c, state, events = collector()

    async def wait(check, **kwargs):
        assert [e.raw_payload["mode"] for e in events] == [
            "directory",
            "detail",
            "detail",
            "finish",
            "manifest",
        ]

    monkeypatch.setattr("empire.features.hot_list.collector.wait_for_archive", wait)
    result = await c.execute()
    assert result["phase"] == "complete" and result["contract"] == CONTRACT
    assert len(str(result).encode()) < 4096


async def test_validation_failure_keeps_failed_date_and_resume_does_not_wait(monkeypatch):
    c, state, events = collector()
    original = c.http.request.side_effect

    def request(*a, **k):
        import json

        if json.loads(k["content"])["Params"][2] == "2009-12-25":
            return httpx.Response(200, json={"ErrorCode": -1})
        return original(*a, **k)

    c.http.request.side_effect = request
    monkeypatch.setattr("empire.features.hot_list.collector.wait_for_archive", AsyncMock())
    with pytest.raises(ValueError):
        await c.execute()
    assert state["cursor"]["last_date"] == DATE and state["cursor"]["index"] == 0
    c.http.request.side_effect = original
    result = await c.execute(baseline_revision=state["revision"])
    assert result["phase"] == "complete"
    assert sum(e.raw_payload["mode"] == "detail" for e in events) == 2


async def test_directory_changed_after_interruption_requires_fresh(monkeypatch):
    c, state, events = collector()
    c.query.day_heads.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await c.execute()
    assert state["cursor"]["directory_hash"]
    c.query.day_heads.side_effect = None
    c.http.request.side_effect = lambda *a, **k: httpx.Response(200, json=directory([DATE]))
    with pytest.raises(ValueError, match="目录已修订"):
        await c.execute(baseline_revision=state["revision"])


async def test_incremental_new_old_gap_and_ninety_day_boundary(monkeypatch):
    import json
    from datetime import datetime, timedelta

    from empire.core.time import CHINA

    # Directory is authoritative: an exposed old date and an old partial date
    # must be fetched even when a newer date is already fully archived.
    today = datetime.now(CHINA).date()
    dates = [(today - timedelta(days=n)).isoformat() for n in (0, 89, 90, 1000, 1001)]
    c, state, events = collector()
    c.query.day_heads.return_value = {
        d: dict(detail_status="partial" if d == dates[3] else "present") for d in dates[:-1]
    }
    c.http.request.side_effect = lambda *a, **k: httpx.Response(
        200, json=directory(dates) if json.loads(k["content"])["Params"][0] == "0" else detail()
    )
    monkeypatch.setattr("empire.features.hot_list.collector.wait_for_archive", AsyncMock())
    await c.execute()
    assert [e.raw_payload["date"] for e in events if e.raw_payload["mode"] == "detail"] == [
        dates[i] for i in (0, 1, 3, 4)
    ]
    # With a lost Redis cursor, SQL heads still supply the same gap plan.
    state.update(revision=0, cursor={})
    events.clear()
    await c.execute()
    assert [e.raw_payload["date"] for e in events if e.raw_payload["mode"] == "detail"] == [
        dates[i] for i in (0, 1, 3, 4)
    ]
    await c.execute(fresh=True, baseline_revision=state["revision"])
    assert [e.raw_payload["date"] for e in events if e.raw_payload["mode"] == "detail"][
        -5:
    ] == dates


async def test_scoped_range_and_scope_conflict(monkeypatch):
    c, state, events = collector()
    c.query.day_heads.return_value = {DATE: dict(detail_status="present")}
    c.confirmation.page_status.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await c.execute(start=DATE, end=DATE)
    assert [e.raw_payload["date"] for e in events if e.raw_payload["mode"] == "detail"] == [DATE]
    assert state["cursor"]["phase"] == "awaiting_archive"
    # Once the whole scope has queued, resume confirms that existing batch.
    c.confirmation.page_status.side_effect = None
    result = await c.execute(start="1990-01-01", baseline_revision=state["revision"])
    assert result["start"] == DATE and result["phase"] == "complete"
