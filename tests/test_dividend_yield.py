"""Independent arithmetic and fail-closed raw-price, calendar and basis counterexamples."""

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.contracts.preparation import CheckEvidence, ComputationContribution
from empire.core.time import CHINA
from empire.features.capital_actions.dividend_yield import calculate_yield, yield_number
from empire.features.capital_actions.event_rules import ActionError
from empire.features.capital_actions.query import CapitalDataPlugin
from empire.features.capital_actions.yield_inputs import denominator_day, price_input
from empire.features.kaipanla.selection import select_plan, validate_request
from tests.test_dividend_distribution import records

SCOPE = dict(codes=["000001"], start="2026-01-01", end="2026-10-20")


def test_independent_manual_arithmetic_and_registration():
    # Hand calculation: 609 / 1000 / 12 * 100 = 609 / 120 = 5.075.
    assert yield_number("0.609", "12") == "5.075"
    assert yield_number("0", "12") == "0"
    q = CapitalDataPlugin("dividends")
    c = q.preparation[-1]
    assert isinstance(c, ComputationContribution) and c.requirement == "dividend_yield"
    assert c.capability == "dividends.query" and c.output_version == q.output_version
    assert not any(
        isinstance(c, ComputationContribution)
        for c in CapitalDataPlugin("rights_issues").preparation
    )


@pytest.mark.parametrize("bad", ["0", "-1", None, "NaN", True])
def test_invalid_denominator_never_zero_or_infinite_yield(bad):
    with pytest.raises(ActionError):
        yield_number("0.609", bad)


def result_rows(rows):
    return SimpleNamespace(mappings=lambda: rows)


def price_case():
    day = date(2026, 10, 20)
    row = dict(
        kind="quote",
        market="SZ",
        code="000001",
        trade_date=day.isoformat(),
        lifecycle={"listing_date": "1991-04-03"},
        data={
            "real": dict(
                time=153833000,
                last_px=12,
                low_px=11,
                high_px=13,
                total_amount=100,
                total_shares=1000,
            )
        },
    )
    head = dict(
        trade_date=day, version_observed_at=datetime(2026, 10, 21, 1), content_hash="a" * 64
    )
    return day, row, head


@pytest.mark.parametrize(
    "damage",
    [
        "none",
        "missing",
        "wrong_security",
        "adjusted",
        "intraday",
        "zero",
        "negative",
        "above_high",
        "preclose_evidence",
        "future_evidence",
        "missing_shares",
        "suspension",
    ],
)
def test_raw_close_and_exact_identity_guards(damage, monkeypatch):
    def suspension(*args):
        if damage == 'suspension':
            raise ValueError('分母日有停牌')
        return {'source': 'tdx'}
    monkeypatch.setattr('empire.features.capital_actions.yield_inputs.closing_price_evidence', suspension)
    day, row, head = price_case()
    if damage == "wrong_security":
        row["code"] = "600000"
    if damage == "intraday":
        row["data"]["real"]["time"] = 145959000
    if damage in ("zero", "negative", "above_high"):
        row["data"]["real"]["last_px"] = {"zero": 0, "negative": -1, "above_high": 14}[damage]
    if damage == "missing_shares":
        row["data"]["real"]["total_shares"] = None
    if damage == "preclose_evidence":
        head["version_observed_at"] = datetime(2026, 10, 20, 14)
    if damage == "future_evidence":
        head["version_observed_at"] = datetime(2099, 1, 1)
    rows = [] if damage == "missing" else [row]
    query = SimpleNamespace(
        kind="adjusted" if damage == "adjusted" else "quote",
        iter_validated_days=lambda *a: iter(rows),
    )
    conn = SimpleNamespace(
        execute=lambda statement, params: result_rows(
            [head]
            if "stock_market_day" in str(statement)
            else [dict(reason="停牌")]
            if damage == "suspension"
            else []
        )
    )
    args = (conn, query, "000001.SZ", day, day, day, [day], datetime(2026, 10, 22, tzinfo=UTC))
    if damage == "none":
        value = price_input(*args)
        assert value["price"] == "12" and value["date"] == day.isoformat()
    else:
        with pytest.raises(ValueError):
            price_input(*args)


def test_share_basis_change_and_same_count_wrong_day_block():
    day, row, head = price_case()
    prior = date(2026, 10, 19)
    old = deepcopy(row)
    old["trade_date"] = prior.isoformat()
    old["data"]["real"]["total_shares"] = 900
    query = SimpleNamespace(kind="quote", iter_validated_days=lambda *a: iter([old, row]))
    conn = SimpleNamespace(execute=lambda *a: result_rows([{**head, "trade_date": prior}, head]))
    with pytest.raises(ActionError, match="股数基准变化"):
        price_input(
            conn,
            query,
            "000001.SZ",
            prior,
            day,
            day,
            [prior, day],
            datetime(2026, 10, 22, tzinfo=UTC),
        )
    with pytest.raises(ActionError, match="缺少精确"):
        price_input(
            conn,
            query,
            "000001.SZ",
            prior,
            day,
            day,
            [date(2026, 10, 18), day],
            datetime(2026, 10, 22, tzinfo=UTC),
        )


def test_nontrade_end_is_explicit_and_unclosed_trade_blocks(monkeypatch):
    monkeypatch.setattr(
        "empire.features.capital_actions.yield_inputs.read_trade_day_cutoff",
        lambda *a: (datetime(2026, 10, 16, 15, 30, tzinfo=CHINA), "official"),
    )
    conn = SimpleNamespace(execute=lambda *a: SimpleNamespace(scalar_one=lambda: 0))
    assert denominator_day(conn, "2026-10-18", datetime(2026, 10, 22, tzinfo=UTC)) == date(
        2026, 10, 16
    )
    conn.execute = lambda *a: SimpleNamespace(scalar_one=lambda: 1)
    with pytest.raises(ActionError, match="尚未到15:30"):
        denominator_day(conn, "2026-10-19", datetime(2026, 10, 19, 6, tzinfo=UTC))
    with pytest.raises(ActionError, match="尚未结束"):
        denominator_day(conn, "2026-10-23", datetime(2026, 10, 22, tzinfo=UTC))


@pytest.mark.parametrize(
    "case", ["passed", "price_missing", "historical", "proof_missing", "proven_empty"]
)
async def test_product_states_and_independent_nominal_output(case):
    checks = [
        CheckEvidence(
            "coverage",
            "fail" if case == "proof_missing" else "pass",
            "unit",
            observed_at=datetime.now(UTC).isoformat(),
        )
    ]
    if case == "historical":
        checks.append(CheckEvidence("temporal", "fail", "缺修订可用日", reason="source_limit"))
    units = {"000001.SZ": [] if case == "proven_empty" else records()}
    inputs = {"000001.SZ": dict(calendar={}, denominator=dict(price="12", date="2026-10-20"))}
    q = SimpleNamespace(
        mysql=SimpleNamespace(
            read=AsyncMock(
                return_value=(
                    checks,
                    {},
                    units,
                    inputs,
                    "缺价格" if case == "price_missing" else "",
                )
            )
        ),
        context=None,
    )
    result = await calculate_yield(q, SCOPE)
    assert result["state"] == (
        "来源受限"
        if case == "historical"
        else "数据阻断"
        if case in ("price_missing", "proof_missing")
        else "已计算"
    )
    if result["state"] == "已计算":
        assert result["securities"][0]["yield_percent"] == (
            "0" if case == "proven_empty" else "5.075"
        )
    else:
        assert result["securities"] == []


def test_bounded_collection_request_exact_market_dates_and_no_saved_policy():
    request = dict(
        securities=["000001.SZ"], start="2026-10-20", end="2026-10-20", proxy_priority=True
    )
    before = deepcopy(request)
    pool = [dict(market="SZ", code="000001"), dict(market="SH", code="600000")]
    stocks, days = select_plan(request, pool, [date(2026, 10, 19), date(2026, 10, 20)])
    assert stocks == pool[:1] and days == [date(2026, 10, 20)] and request == before
    with pytest.raises(ValueError):
        validate_request({**request, "securities": ["000001.SZ"] * 2})
    with pytest.raises(ValueError):
        select_plan({**request, "securities": ["000001.SH"]}, pool, days)


@pytest.mark.parametrize('fresh', [True, False])
async def test_redis_unavailable_keeps_actual_sql_evidence_and_never_refreshes_it(fresh):
    stamp = datetime.now(UTC) - timedelta(days=1 if fresh else 4)
    checks = tuple(CheckEvidence(k, 'pass' if k != 'freshness' or fresh else 'fail',
        'SQL', observed_at=stamp.isoformat()) for k in ('fields','keys','coverage','quality','freshness','temporal'))
    store = SimpleNamespace(prefix='test', client=SimpleNamespace(hget=AsyncMock(side_effect=OSError('offline'))))
    q = SimpleNamespace(mysql=SimpleNamespace(read=AsyncMock(return_value=(checks,
        {'SZ:000001': ('a'*64, stamp)}, {'000001.SZ': records()},
        {'000001.SZ':dict(calendar={},denominator=dict(price='12',date='2026-10-20'))}, ''))),
        context=SimpleNamespace(optional=lambda _: store), kind='dividends', source='tdx',
        job_key='tdx-dividends-v1', archive_settings={})
    result = await calculate_yield(q, SCOPE)
    assert result['state'] == ('已计算' if fresh else '数据阻断')
    assert result['observed_at'] == stamp.isoformat()
