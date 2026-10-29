import copy
import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.industry_margin.collector import IndustryMarginCollector
from empire.features.industry_margin.contract import dates, plan
from empire.features.industry_margin.source import COLUMNS, parse
from tests.prefetch_source import prefetch_http


def response(rows=None):
    rows = (
        rows
        if rows is not None
        else [[100, 200, 30, 20, 4, 5, 6, "煤炭"], [80, 90, 10, 9, 1, 2, 3, "石油"]]
    )
    return {
        "ErrorCode": 0,
        "ResultSets": [{"ColName": COLUMNS, "Count": len(rows), "Content": rows}],
    }


def test_source_complete_set_and_equal_count_duplicate():
    rows = parse(response())
    assert len(rows) == 2 and rows[0][1] == "100"
    broken = response()
    broken["ResultSets"][0]["Content"][1] = broken["ResultSets"][0]["Content"][0]
    with pytest.raises(ValueError, match="重复"):
        parse(broken)
    assert parse(response([])) == []
    broken = response()
    broken["ResultSets"][0]["Count"] += 1
    with pytest.raises(ValueError):
        parse(broken)


@pytest.mark.parametrize("value", [True, -1e20, float("inf"), "0.000000001"])
def test_source_rejects_invalid_numbers(value):
    body = response()
    body["ResultSets"][0]["Content"][0][0] = value
    with pytest.raises(ValueError):
        parse(body)


def test_null_retained_latest_date_and_shape():
    body = response()
    body["ResultSets"][0]["Content"][0][0] = None
    assert parse(body)[0][1] is None
    body["ResultSets"][0]["Content"][0][5] = -1.6449
    assert parse(body)[0][6] == "-1.6449"
    latest = {
        "ErrorCode": 0,
        "ResultSets": [{"ColName": ["mxt"], "Count": 1, "Content": [["20261028"]]}],
    }
    assert parse(latest, latest=True, through="2026-10-30") == "2026-10-28"
    with pytest.raises(ValueError):
        parse(latest, latest=True, through="2026-10-27")
    for bad in ({"ErrorCode": 1}, {}, {"ErrorCode": False, "ResultSets": []}):
        with pytest.raises(ValueError):
            parse(bad)


def test_complete_date_capacity_and_name_identity():
    maximum = [[1, 2, 3, 4, 5, 6, 7, f"industry-{i:03d}"] for i in range(256)]
    assert len(parse(response(maximum))) == 256
    with pytest.raises(ValueError, match="超限"):
        parse(response(maximum + [[1, 2, 3, 4, 5, 6, 7, "extra"]]))
    with pytest.raises(ValueError):
        parse(response([[1, 2, 3, 4, 5, 6, 7, "coal "]]))


async def test_archive_wait_failure_keeps_published_phase_without_redownload(monkeypatch):
    c, state, events = collector()
    wait = AsyncMock(side_effect=RuntimeError("archive unavailable"))
    monkeypatch.setattr("empire.features.industry_margin.collector.wait_for_archive", wait)
    with pytest.raises(RuntimeError, match="archive unavailable"):
        await c.execute(start="2016-01-04", end="2016-01-04")
    assert state["cursor"]["phase"] == "awaiting_archive" and len(events) == 1
    c.http.request.reset_mock()
    wait.side_effect = None
    await c.execute(start="2016-01-04", end="2016-01-04", baseline_revision=state["revision"])
    assert c.http.request.call_count == 0 and state["cursor"]["phase"] == "complete"


def test_initial_unchanged_new_unit_loss_and_full_90_day_revision_cycle():
    full = dates("2016-01-01", "2026-10-28")
    assert plan(full[0], full[-1], set(), "2026-10-30") == full
    ordinary = plan(full[0], full[-1], set(full), "2026-10-30")
    assert len(ordinary) < 60 and set(full[-7:]) <= set(ordinary)
    added = plan(full[0], "2026-10-29", set(full), "2026-10-30")
    assert set(added) - set(ordinary) == {"2026-10-29"}
    missing = "2018-01-03"
    assert missing in plan(full[0], full[-1], set(full) - {missing}, "2026-10-30")
    # Redis loss uses the same SQL date set, not an empty in-memory checkpoint.
    assert plan(full[0], full[-1], set(full), "2026-10-30") == ordinary
    seen = set()
    for i in range(90):
        seen.update(
            plan(full[0], full[-1], set(full), (date(2026, 10, 30) + timedelta(days=i)).isoformat())
        )
    assert seen == set(full)


def collector():
    c = IndustryMarginCollector()
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
    c.query = SimpleNamespace(covered=AsyncMock(return_value=set()))
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={"status": "complete"}))

    def fetch(*a, **kw):
        params = json.loads(kw["content"])["Params"]
        body = (
            response()
            if params[0] == "1"
            else {
                "ErrorCode": 0,
                "ResultSets": [{"ColName": ["mxt"], "Count": 1, "Content": [["20261028"]]}],
            }
        )
        return httpx.Response(200, json=body)

    c.http = prefetch_http(request=AsyncMock(side_effect=fetch))
    return c, state, events


async def test_publish_all_before_archive_and_resume_failure(monkeypatch):
    c, state, events = collector()
    original = c.http.request.side_effect

    def failed(*a, **kw):
        if json.loads(kw["content"])["Params"] == ["1", "20160102"]:
            return httpx.Response(200, json={"ErrorCode": 1})
        return original(*a, **kw)

    c.http.request.side_effect = failed

    async def wait(*a, **kw):
        assert len(events) == 3

    monkeypatch.setattr("empire.features.industry_margin.collector.wait_for_archive", wait)
    with pytest.raises(ValueError):
        await c.execute(start="2016-01-01", end="2016-01-03")
    assert state["cursor"]["last_date"] == "2016-01-01" and len(events) == 1
    c.http.request.side_effect = original
    c.http.request.reset_mock()
    await c.execute(start="2016-01-01", end="2016-01-03", baseline_revision=state["revision"])
    assert c.http.request.call_count == 2
    assert state["cursor"]["phase"] == "complete"
    assert len(json.dumps(state).encode()) < 1024


async def test_range_conflict_and_no_historical_redownload_after_redis_loss(monkeypatch):
    c, state, events = collector()
    monkeypatch.setattr("empire.features.industry_margin.collector.wait_for_archive", AsyncMock())
    existing = set(dates("2016-01-01", "2026-10-28"))
    c.query.covered.return_value = existing
    await c.execute()
    assert c.http.request.call_count < 70
    state.update(revision=0, cursor={})
    c.http.request.reset_mock()
    await c.execute()
    assert c.http.request.call_count < 70
    state["cursor"]["phase"] = "fetch"
    with pytest.raises(ValueError, match="冲突"):
        await c.execute(start="2017-01-01", baseline_revision=state["revision"])
