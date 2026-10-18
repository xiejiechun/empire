import asyncio
import copy
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.bootstrap import build_manager
from empire.contracts.data import make_envelope
from empire.contracts.index_prices import JOB, number
from empire.core.time import CHINA
from empire.plugins.collectors.ths_index_prices import ThsIndexPriceCollector
from empire.plugins.collectors.ths_index_prices_source import annual, recent
from empire.plugins.datasets.index_prices import fingerprint_plan, normalize
from tests.prefetch_source import prefetch_http
from tests.test_capital_lifecycle import Publisher

CODE = "399411"
ROWS = [
    ["2025-12-30", "10", "12", "9", "11", "100", "1000"],
    ["2025-12-31", "11", "13", "10", "12", "200", "2000"],
    ["2026-01-02", "12", "14", "11", "13", "300", "3000"],
]


def source(unit="last", rows=None, code=CODE, **changes):
    rows = ROWS if rows is None else rows
    body = dict(
        data=";".join(",".join([r[0].replace("-", "")] + ["" if v is None else v for v in r[1:]] + ["", "", "", "0"]) for r in rows)
    )
    if unit == "last":
        body.update(start="20251230", year={"2025": 2, "2026": 1}, total="3", num=len(rows))
    body.update(changes)
    return f"quotebridge_v4_line_zs_{code}_01_{unit}({json.dumps(body)})"


def envelope(rows=None, mode="full", year=2025, page=1):
    return make_envelope(
        source="ths",
        dataset="index.price.year",
        business_key=f"{CODE}:{year}",
        job_key=JOB,
        batch_id="test",
        run_id="test",
        payload=dict(
            page=page,
            code=CODE,
            year=year,
            mode=mode,
            source_count=2,
            start="2025-12-30",
            end="2026-01-02",
            rows=copy.deepcopy(ROWS[:2] if rows is None else rows),
        ),
    )


def collector():
    c = ThsIndexPriceCollector()

    class StatePublisher(Publisher):
        async def advance_checkpoint(self, *, expected_revision, cursor, **kw):
            assert expected_revision == self.state["revision"]
            self.state = dict(revision=expected_revision + 1, cursor=copy.deepcopy(cursor))
            return copy.deepcopy(self.state)

    c.ingest = StatePublisher()
    c.session = SimpleNamespace(headers=lambda _: {})
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value={"status": "complete"}))
    c.query = SimpleNamespace(
        catalog=AsyncMock(return_value=[dict(code=CODE, name="红利100")]),
        year_heads=AsyncMock(return_value={}),
    )

    def request(method, url, **kw):
        unit = url.rsplit("/", 1)[1].split(".")[0]
        assert kw["retry_not_found"] == (unit != "last")
        assert kw["allow_not_found"] == (unit == "last")
        assert kw["project_id"] == "ths-index-prices" and kw["allowed_domains"] == (
            "10jqka.com.cn",
        )
        rows = ROWS if unit == "last" else [r for r in ROWS if r[0][:4] == unit]
        return httpx.Response(200, content=source(unit, rows).encode())

    c.http = prefetch_http(request=AsyncMock(side_effect=request), response_policy=lambda _: None)
    return c


def test_annual_identity_count_and_numeric_contract():
    snapshot = recent(source(), CODE)
    assert annual(source(2025, ROWS[:2]), CODE, 2025, snapshot) == ROWS[:2]
    assert number("1.0000000", True) == "1"
    for value in ("NaN", "-1", "1e2", "1.1234567", "1000000000000"):
        with pytest.raises(ValueError):
            number(value, True)
    e = envelope()
    assert fingerprint_plan(e, normalize(e)) == fingerprint_plan(
        e.model_copy(update={"batch_id": "other"}), normalize(e)
    )
    assert normalize(e)["row_count"] == 2


@pytest.mark.parametrize(
    "body",
    [
        source(rows=ROWS[:1] + ROWS[:1] + ROWS[2:]),
        source(rows=list(reversed(ROWS))),
        source(code="399001"),
        source()[:-1],
        "<html>login</html>",
        source(total="4"),
        source(year={"2025": 3, "2026": 1}),
    ],
)
def test_invalid_recent_does_not_pass(body):
    with pytest.raises(ValueError):
        recent(body, CODE)


def test_same_count_different_overlap_set_and_cross_year_fail():
    snapshot = recent(source(), CODE)
    changed = copy.deepcopy(ROWS[:2])
    changed[1][0] = "2025-12-29"
    for rows in (changed, [ROWS[0]], ROWS):
        with pytest.raises(ValueError):
            annual(source(2025, rows), CODE, 2025, snapshot)
    replaced = copy.deepcopy(ROWS[:2])
    replaced[1][4] = "12.5"
    with pytest.raises(ValueError, match="集合或内容"):
        annual(source(2025, replaced), CODE, 2025, snapshot)


def test_intraday_last_is_not_archived_and_count_adjusts():
    result = recent(source(), CODE, datetime(2026, 1, 2, 12, tzinfo=CHINA))
    assert result["end"] == "2025-12-31" and result["years"] == {"2025": 2} and result["total"] == 2


def test_after_close_placeholder_is_deferred_without_losing_history():
    rows = copy.deepcopy(ROWS)
    rows[-1] = ["2026-01-02", None, None, None, "12.9", "0", None]
    now = datetime(2026, 1, 2, 16, tzinfo=CHINA)
    snapshot = recent(source(rows=rows), CODE, now)
    assert snapshot["end"] == "2025-12-31" and snapshot["total"] == 2
    assert snapshot["years"] == {"2025": 2}
    # The same values on a past date are preserved as source data.
    later = recent(source(rows=rows), CODE, datetime(2026, 1, 3, 16, tzinfo=CHINA))
    assert later["rows"][-1] == rows[-1] and later["total"] == 3


def test_only_latest_annual_content_uses_valid_recent_snapshot():
    now = datetime(2026, 1, 2, 16, tzinfo=CHINA)
    snapshot = recent(source(), CODE, now)
    placeholder = [["2026-01-02", None, None, None, "12.9", "0", None]]
    assert annual(source(2026, placeholder), CODE, 2026, snapshot, now) == ROWS[2:]
    for wrong in ([['2026-01-01', *placeholder[0][1:]]], [placeholder[0], placeholder[0]], []):
        with pytest.raises(ValueError):
            annual(source(2026, wrong), CODE, 2026, snapshot, now)
    assert annual(source(2026, placeholder), CODE, 2026, snapshot,
                  datetime(2026, 1, 3, 16, tzinfo=CHINA)) == ROWS[2:]
    conflict = copy.deepcopy(ROWS[2:])
    conflict[0][4] = "13.1"
    assert annual(source(2026, conflict), CODE, 2026, snapshot, now) == ROWS[2:]
    assert annual(source(2026, conflict), CODE, 2026, snapshot,
                  datetime(2026, 1, 3, 16, tzinfo=CHINA)) == ROWS[2:]


@pytest.mark.parametrize("now", [datetime(2026, 10, 13, 0, 5, tzinfo=CHINA),
                                 datetime(2026, 10, 18, 12, tzinfo=CHINA)])
def test_midnight_and_closed_market_latest_conflict(now):
    last = [["2026-10-09", "4595.26", "4683.05", "4485.92", "4670.87", "1965300500", "42125930000"],
            ["2026-10-12", "4659.58", "4685.71", "4607.92", "4613.73", "1778615800", "37021602000"]]
    snapshot = recent(source(rows=last, code="399291", start="20261009",
                             year={"2026": 2}, total="2"), "399291", now)
    stale = copy.deepcopy(last)
    stale[-1][3:] = ["4617.14", "4645.81", "1203460010", "25282274000"]
    assert annual(source(2026, stale, code="399291"), "399291", 2026, snapshot, now) == last
    stale[0][4] = "4660"
    with pytest.raises(ValueError, match="集合或内容") as caught:
        annual(source(2026, stale, code="399291"), "399291", 2026, snapshot, now)
    assert caught.value.source_metadata["trade_date"] == "2026-10-09"


def test_historical_placeholder_last_is_not_authoritative():
    rows = copy.deepcopy(ROWS)
    rows[-1] = ["2026-01-02", None, None, None, "12.9", "0", None]
    snapshot = recent(source(rows=rows), CODE, datetime(2026, 1, 3, tzinfo=CHINA))
    with pytest.raises(ValueError, match="集合或内容"):
        annual(source(2026, ROWS[2:]), CODE, 2026, snapshot)


async def test_publication_continues_until_whole_round_archive_wait():
    c = collector()

    async def confirm(*args):
        assert len(c.ingest.events) == 3 and c.http.request.await_count == 3
        return {"status": "complete"}

    c.confirmation.page_status.side_effect = confirm
    result = await c.execute()
    assert result["phase"] == "complete" and result["collected"] == 3
    assert c.ingest.events[0].dataset == "index.price.status"
    assert [e.raw_payload.get("year") for e in c.ingest.events[1:]] == [2025, 2026]


async def test_existing_years_only_last_one_request_and_partial_publish():
    c = collector()
    c.query.year_heads.return_value = {
        "2025": dict(source_count=2, complete=True, last_date="2025-12-31"),
        "2026": dict(source_count=1, complete=True, last_date="2026-01-02"),
    }
    await c.execute()
    assert c.http.request.await_count == 1
    assert all(e.raw_payload["mode"] == "recent" for e in c.ingest.events[1:])


async def test_placeholder_never_replaces_archived_today_or_annual_proof():
    c = collector()
    snapshot = dict(start=ROWS[0][0], end=ROWS[1][0], years={"2025": 2,"2026": 183},
                    total=185, rows=ROWS[:2], deferred_day="2026-10-12")
    c.fetch = AsyncMock(return_value=snapshot)
    c.query.year_heads.return_value = {
        "2025": dict(source_count=2, complete=True, last_date="2025-12-31"),
        "2026": dict(source_count=184, complete=True, last_date="2026-10-12"),
    }
    await c.execute()
    assert all(e.raw_payload.get("year") != 2026 for e in c.ingest.events)


async def test_failure_retains_year_checkpoint_and_resumes():
    c = collector()
    original = c.http.request.side_effect

    def broken(method, url, **kw):
        return (
            httpx.Response(200, content=b"broken")
            if "/2026.js" in url
            else original(method, url, **kw)
        )

    c.http.request.side_effect = broken
    with pytest.raises(ValueError):
        await c.execute()
    assert c.ingest.state["cursor"]["next_year"] == 2026
    assert len(c.ingest.events) == 2
    c.http.request.side_effect = original
    await c.execute()
    years = [e.raw_payload.get("year") for e in c.ingest.events]
    assert years.count(2025) == 2  # Initial full and recent replay; no second full history read.
    assert c.ingest.state["cursor"]["phase"] == "complete"


async def test_cancel_final_archive_resumes_without_source_request():
    c = collector()
    gate = asyncio.Event()

    async def confirm(*args):
        await gate.wait()

    c.confirmation.page_status.side_effect = confirm
    task = asyncio.create_task(c.execute())
    async with asyncio.timeout(3):
        while c.stats["status"] != "awaiting_archive":
            await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    c.http.request.reset_mock()
    c.confirmation.page_status.side_effect = None
    c.confirmation.page_status.return_value = {"status": "complete"}
    await c.execute(fresh=True)
    assert not c.http.request.called


async def test_404_only_declares_interface_unavailable():
    c = collector()
    c.http.request.return_value = httpx.Response(404, content=b"not found")
    c.http.request.side_effect = None
    result = await c.execute()
    assert result["unavailable"] == 1 and len(c.ingest.events) == 1
    assert c.ingest.events[0].raw_payload["snapshot"] == {}


def test_registration_scopes_and_lazy_page():
    from empire.contracts.preparation_scope import PreparationScope

    scope = PreparationScope.parse(dict(codes=["601139"], index_codes=["1A0001"]))
    assert scope.codes == ("601139",) and scope.index_codes == ("1A0001",)
    manager = build_manager(dict(redis={}, mysql={}, archive={}, ingest={}, rate_groups={}))
    task = manager.entries["collection.control"].plugin.definitions["ths-index-prices"]
    assert task.parallel_downloads and task.default_schedule.mode == "daily"
    page = manager.entries["ui.index_prices"].plugin.create_pages()[0]
    assert page.catalogued and page.management.context.task_id == "ths-index-prices"


async def test_shared_http_explicit_404_contract_keeps_other_errors():
    from empire.plugins.infra.http import HttpService
    from empire.plugins.infra.routing import USE_PROXY
    from tests.test_http import MemoryPermits, groups

    attempts = []

    def missing(request):
        attempts.append(request.url)
        return httpx.Response(404)

    service = HttpService(
        MemoryPermits(),
        "test",
        groups(1),
        transport=httpx.MockTransport(missing),
    )
    token = USE_PROXY.set(False)  # Isolated MockTransport protocol test, no real source request.
    try:
        response = await service.request(
            "GET",
            "https://sina.com.cn/missing",
            allowed_domains=("sina.com.cn",),
            allow_not_found=True,
            max_retries=0,
        )
        assert response.status_code == 404
        response.close()
        with pytest.raises(httpx.HTTPStatusError):
            await service.request(
                "GET",
                "https://sina.com.cn/missing",
                allowed_domains=("sina.com.cn",),
                max_retries=100,
            )
        assert len(attempts) == 2  # Other sources still fail 404 immediately, even with a large budget.
        with pytest.raises(ValueError):
            await service.request(
                "GET",
                "https://sina.com.cn/missing",
                allowed_domains=("sina.com.cn",),
                allow_not_found=1,
            )
        for options in ({"retry_not_found": 1}, {"retry_not_found": True, "allow_not_found": True}):
            with pytest.raises(ValueError):
                await service.request("GET", "https://sina.com.cn/missing",
                                      allowed_domains=("sina.com.cn",), **options)
    finally:
        USE_PROXY.reset(token)
        await service.close()


@pytest.mark.parametrize("mode", ["success", "cancel", "bad_first"])
async def test_annual_prefetch_order_and_failed_cancelled_budget_recovery(mode):
    c = collector()
    annual_rows = [[f"{y}-01-02", *ROWS[0][1:]] for y in (2024, 2025, 2026)]
    gate = asyncio.Event()
    completed, responses = [], []

    async def request(method, address, **options):
        unit = address.rsplit("/", 1)[1].split(".")[0]
        if unit == "last":
            body = source(
                rows=annual_rows, start="20240102", year={"2024": 1, "2025": 1, "2026": 1}
            )
        else:
            if unit == "2024":
                await gate.wait()
            completed.append(unit)
            body = (
                "broken"
                if mode == "bad_first" and unit == "2024"
                else source(unit, [annual_rows[int(unit) - 2024]])
            )
        response = httpx.Response(200, content=body.encode())
        responses.append(response)
        return response

    c.http = prefetch_http(request=AsyncMock(side_effect=request))
    c.http.parallelism.return_value = 3
    task = asyncio.create_task(c.execute())
    try:
        async with asyncio.timeout(3):
            while completed != ["2025", "2026"]:
                await asyncio.sleep(0)
        assert len(c.ingest.events) == 1 and c.ingest.state["cursor"]["next_year"] == 1990
        assert c.confirmation.page_status.await_count == 0
        if mode == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            gate.set()
            if mode == "bad_first":
                with pytest.raises(ValueError):
                    await task
                assert c.ingest.state["cursor"]["next_year"] == 1990
            else:
                await task
                assert [e.raw_payload["year"] for e in c.ingest.events[1:]] == [2024, 2025, 2026]
        assert c.http.buffer_budget.used == c.http.buffer_budget.waiting == 0
        assert all(r.is_closed for r in responses)
    finally:
        gate.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


def test_source_missing_ohl_preserves_real_close_volume_amount():
    rows = [["2004-01-02", None, None, None, "1053.27", "176978490", "976973690"]]
    snapshot = dict(years={"2004": 1}, start="2004-01-02", end="2004-01-02", rows=rows)
    assert annual(source(2004, rows, code="1B0070"), "1B0070", 2004, snapshot) == rows
    from empire.contracts.index_prices import validate_rows
    validate_rows(rows, 2004)
    for field in (4, 5):
        broken = copy.deepcopy(rows)
        broken[0][field] = None
        with pytest.raises(ValueError):
            annual(source(2004, broken, code="1B0070"), "1B0070", 2004, snapshot)
    partial = [["2004-01-02", None, "1100", "1000", "1053.27", "176978490", "976973690"]]
    validate_rows(partial, 2004)
    for field, value in ((1,"0"), (1,"NaN")):
        broken = copy.deepcopy(partial)
        broken[0][field] = value
        with pytest.raises(ValueError):
            validate_rows(broken, 2004)


def test_source_contradiction_preserves_values_and_exposes_quality():
    from empire.contracts.index_prices import price_relation_valid, validate_rows
    rows = [["2020-07-29", "3228.96", "3300", "3265.46", "3300", "32470125000", "452959530000"]]
    snapshot = dict(years={"2020": 1}, start=rows[0][0], end=rows[0][0], rows=rows)
    assert annual(source(2020, rows, code="1C0003"), "1C0003", 2020, snapshot) == rows
    validate_rows(rows, 2020)
    assert not price_relation_valid(rows[0][1:5])
    assert price_relation_valid([None, "3300", "3265.46", "3300"])
    assert not price_relation_valid([None, "3200", "3265.46", "3300"])
    assert not price_relation_valid(["3300", "3300", "3265.46", "3200"])


def test_empty_source_amount_is_unknown_not_zero():
    rows = [["2009-12-31", "3326.44", "3326.44", "3326.44", "3326.44", "0", None]]
    snapshot = dict(years={"2009": 1}, start=rows[0][0], end=rows[0][0], rows=rows)
    assert annual(source(2009, rows, code="399303"), "399303", 2009, snapshot) == rows
    for field, value in ((5, None), (4, None), (6, "NaN"), (6, "1e5"), (6, "0.00001")):
        broken = copy.deepcopy(rows)
        broken[0][field] = value
        with pytest.raises(ValueError):
            annual(source(2009, broken, code="399303"), "399303", 2009, snapshot)


@pytest.mark.parametrize("column", [5, 6])
def test_signed_source_quantity_is_quality_not_parse_failure(column):
    from empire.contracts.index_prices import validate_rows, volume_amount_valid
    from empire.plugins.collectors.ths_index_prices_source import parse
    rows = [["2014-12-05", "3813.84", "3823.18", "3641.33", "3756.47", "94777491000", "798120910000"]]
    rows[0][column] = "-798120910000"
    _, parsed = parse(source(2014, rows, code="399317"), "399317", 2014)
    assert parsed == rows and not volume_amount_valid(parsed[0][5:7])
    validate_rows(parsed, 2014)
    assert number("+000.00") == number("-0.0000") == "0"
    assert volume_amount_valid(["0", None])
    with pytest.raises(ValueError, match="越界"):
        number("-100000000000000000000")


@pytest.mark.parametrize("value", ["NaN", "--1", "1.00001", "-100000000000000000000"])
async def test_numeric_failure_identifies_field_and_preserves_checkpoint(value):
    c = collector()
    changed = copy.deepcopy(ROWS[:2])
    changed[0][6] = value
    c.http.request.side_effect = lambda *a, **kw: httpx.Response(200, content=source(2025, changed).encode())
    before = copy.deepcopy(c.ingest.state)
    with pytest.raises(ValueError, match="399411 2025-12-30 amount"):
        await c.fetch(CODE, 2025, dict(years={"2025": 2}, start=ROWS[0][0], end=ROWS[1][0], rows=[]))
    metadata = c.records.add_error.call_args.kwargs["metadata"]
    assert metadata == dict(index_code=CODE, trade_date="2025-12-30", field="amount",
                            source_value=value, source_value_truncated=False)
    assert c.ingest.state == before
