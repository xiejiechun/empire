import copy
from datetime import date, timedelta
from decimal import Decimal

import pytest

from empire.features.market_margin.contract import STARTS, pack, unpack, validate
from empire.features.market_margin.source import parse


def response(code="99"):
    first = date.fromisoformat(STARTS[code])
    item = dict(
        rzye=100,
        rqye=20,
        rzmre=30,
        rzjmr=-5,
        rqjmc=-10,
        jmrzz="--",
        jmczz="--",
        zb="0.0000012121262302321",
    )
    if code == "99":
        item["lr"] = 120
    return dict(
        status_code=0,
        data=dict(
            date=[first.isoformat(), (first + timedelta(days=1)).isoformat()],
            item=[dict(item), dict(item)],
        ),
    )


def test_source_exact_decimal_units_and_roundtrip():
    for code in STARTS:
        rows = parse(response(code), "2026-10-30", code)
        assert rows[0][1:6] == ["100", "20", "30", "-5", "-10"]
        assert rows[0][6:8] == [None, None]
        assert Decimal(rows[0][8]) == Decimal("0.0000012121262302321")
        assert unpack(pack(rows)) == rows


@pytest.mark.parametrize(
    "kind",
    [
        "same_count_duplicate",
        "length",
        "empty",
        "start",
        "order",
        "future",
        "field",
        "unknown",
        "negative",
        "null",
        "precision",
        "status",
    ],
)
def test_source_failure_never_silently_truncates(kind):
    b = response()
    d = b["data"]
    if kind == "same_count_duplicate":
        d["date"][1] = d["date"][0]
    elif kind == "length":
        d["item"].pop()
    elif kind == "empty":
        d.update(date=[], item=[])
    elif kind == "start":
        d["date"][0] = "2010-03-30"
    elif kind == "order":
        d["date"].reverse()
    elif kind == "future":
        d["date"][1] = "2027-01-01"
    elif kind == "field":
        d["item"][0].pop("rqjmc")
    elif kind == "unknown":
        d["item"][0]["future_field"] = 2
    elif kind == "negative":
        d["item"][0]["rzye"] = -1
    elif kind == "null":
        d["item"][0]["rzye"] = None
    elif kind == "precision":
        d["item"][0]["rzye"] = "1.000000001"
    else:
        b["status_code"] = 1
    with pytest.raises(ValueError):
        parse(b, "2026-10-30", "99")


def test_maximum_unit_and_wire_bounds():
    rows = parse(response(), "2026-10-30", "99")
    rows = [
        [(date(2010, 3, 31) + timedelta(days=i)).isoformat(), *rows[0][1:]] for i in range(10000)
    ]
    assert validate(unpack(pack(rows)), "2040-01-01", "99") == rows
    bad = copy.deepcopy(pack(rows))
    bad["size"] -= 1
    with pytest.raises(ValueError):
        unpack(bad)


@pytest.mark.parametrize("mode", ["bad_first", "cancel", "success"])
async def test_parallel_market_frontier_cancel_and_resume(mode):
    import asyncio
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import httpx

    from empire.features.market_margin.collector import MarketMarginCollector
    from empire.features.market_margin.query import MarketMarginDataPlugin
    from tests.prefetch_source import prefetch_http
    from tests.test_capital_lifecycle import Publisher

    c = MarketMarginCollector()
    c.ingest = Publisher()
    c.query = MarketMarginDataPlugin()
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={"status": "complete"}))
    gate = asyncio.Event()
    seen, responses = [], []

    async def request(method, url, **kw):
        code = url.rstrip("/").split("/")[-1]
        seen.append(code)
        assert method == "GET" and kw["allowed_domains"] == ("10jqka.com.cn",)
        if code == "99":
            await gate.wait()
        b = response(code)
        if mode == "bad_first" and code == "99":
            b["data"]["date"][1] = b["data"]["date"][0]
        r = httpx.Response(200, json=b)
        responses.append(r)
        return r

    c.http = prefetch_http(request=AsyncMock(side_effect=request))
    c.http.parallelism.return_value = 4
    task = asyncio.create_task(c.execute())
    try:
        async with asyncio.timeout(3):
            while len(seen) < 4:
                await asyncio.sleep(0)
        assert not c.ingest.events  # completed later markets cannot cross first unit
        if mode == "cancel":
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        else:
            gate.set()
            if mode == "bad_first":
                with pytest.raises(ValueError):
                    await task
                assert not c.ingest.events and c.ingest.state["revision"] == 0
            else:
                await task
                assert [e.business_key for e in c.ingest.events] == ["99", "3", "2", "4"]
                assert c.ingest.state["cursor"]["phase"] == "complete"
        assert c.http.buffer_budget.used == c.http.buffer_budget.waiting == 0
        assert all(r.is_closed for r in responses)
    finally:
        gate.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
