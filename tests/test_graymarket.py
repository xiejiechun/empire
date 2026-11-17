"""Source semantics and daily completeness, including discovered counterexamples."""

import copy
import json
from decimal import Decimal

import pytest

from empire.features.graymarket.contract import MAX_ROWS, number, plan, validate
from empire.features.graymarket.source import DayAssembly, decode, params, parse


def source_row(index):
    dark, visible = 5000 - index, -100
    return {"3": 0, "4": f"{index:06d}", "5": 153439, "6": dark, "7": visible,
            "8": dark + visible, "11": Decimal("0.12712"), "13": 71540,
            "14": Decimal("-0.09572"), "16": "测试证券", "21": index + 270}


def response(total=101, page=1, stamp=20261102):
    start = (page - 1) * 100 + 1
    return {"errid": 0, "errmsg": "success", "1": stamp, "2": total,
            "data": [source_row(i) for i in range(start, min(start + 100, total + 1))]}


def parsed(body, page=1, requested="2026-11-02"):
    return parse(body, page=page, requested=requested, through="2026-11-03")


def test_request_contract_and_discovery():
    assert params()["date"] == ""
    assert params("2026-11-02", 2) == dict(version=101, cver=100, date="20261102",
        StartPage=2, NumPerPage=100, sortflag=16, desc=1, market="", datetype="")
    assert parsed(response(), requested=None).date == "2026-11-02"
    for page in (True, 0, 101, -1, "1"):
        with pytest.raises(ValueError):
            params("2026-11-02", page)
    with pytest.raises(ValueError):
        params(None, 2)


@pytest.mark.parametrize("code,market,expected", [
    ("920992", 0, "920992.BJ"), ("000001", 0, "000001.SZ"),
    ("300001", 0, "300001.SZ"), ("600000", 1, "600000.SH"),
])
def test_source_route_zero_does_not_mean_shenzhen(code, market, expected):
    body = response(total=1)
    body['data'][0].update({'3': market, '4': code})
    assert parsed(body).rows[0][0] == expected


def test_unverified_route_zero_code_family_fails_closed():
    body = response(total=1)
    body['data'][0]['4'] = '830001'
    with pytest.raises(ValueError, match='代码族'):
        parsed(body)


@pytest.mark.parametrize("total", [1, 99, 100, 101, 200, 5377, MAX_ROWS])
def test_complete_day_exact_page_lengths_and_noncontiguous_source_ranks(total):
    first = parsed(response(total))
    assembly = DayAssembly(first)
    for page in range(2, first.pages + 1):
        assembly.add(parsed(response(total, page), page))
    rows = assembly.finish()
    assert len(rows) == total == len({r[0] for r in rows})
    assert rows[0] == ["000001.SZ", "测试证券", "4999", "-100", "4899",
                       "0.12712", "71.54", "-0.09572", "153439", 271]
    assert first.pages == (total + 99) // 100


def test_date_fallback_not_mislabeled_as_requested_day():
    body = response(stamp=20261030)
    with pytest.raises(ValueError, match="实际日期"):
        parsed(body, requested="2026-11-01")
    assert parsed(body, requested=None).date == "2026-10-30"
    with pytest.raises(ValueError, match="实际日期"):
        parsed(response(stamp=20261104), requested=None)


@pytest.mark.parametrize("body", [{}, {"errid": -2, "errmsg": "no data"},
    {"errid": -2, "errmsg": "findn't code"}, {"errid": False}, {"errid": "0"}])
def test_source_errors_never_become_empty_day(body):
    with pytest.raises(ValueError):
        parsed(body)


@pytest.mark.parametrize("total", [0, -1, True, "101", MAX_ROWS + 1])
def test_total_contract(total):
    body = response()
    body["2"] = total
    with pytest.raises(ValueError):
        parsed(body)


@pytest.mark.parametrize("mutation", ["duplicate", "short", "long"])
def test_page_corruption(mutation):
    body = response()
    if mutation == "duplicate":
        body["data"][1] = copy.deepcopy(body["data"][0])
    elif mutation == "short":
        body["data"].pop()
    elif mutation == "long":
        body["data"].append(source_row(101))
    with pytest.raises(ValueError):
        parsed(body)


def test_acquisition_order_is_not_a_money_rank_and_still_checks_identity():
    body = response(total=2)
    body["data"].reverse()
    assert len(DayAssembly(parsed(body)).finish()) == 2
    body["data"][1] = copy.deepcopy(body["data"][0])
    with pytest.raises(ValueError, match="重复"):
        parsed(body)


def test_cross_page_duplicate_with_unchanged_total_is_rejected():
    assembly = DayAssembly(parsed(response()))
    second = response(page=2)
    second["data"][0]["4"] = "000100"
    with pytest.raises(ValueError, match="跨页证券重复"):
        assembly.add(parsed(second, 2))


def test_page_gap_repeat_total_change_and_boundary_order():
    assembly = DayAssembly(parsed(response()))
    with pytest.raises(ValueError, match="未收齐"):
        assembly.finish()
    with pytest.raises(ValueError, match="分页"):
        assembly.add(parsed(response()))
    with pytest.raises(ValueError, match="分页"):
        assembly.add(parsed(response(total=102, page=2), 2))
    second = response(page=2)
    second["data"][0]["6"] = 99999
    second["data"][0]["8"] = 99899
    assembly.add(parsed(second, 2))
    assert len(assembly.finish()) == 101  # Acquisition order is not money rank.


@pytest.mark.parametrize(("field", "value"), [
    ("3", True), ("3", 90), ("4", "1"), ("4", 1), ("16", ""), ("16", " a"),
    ("16", "a" * 65), ("16", "a\x00"), ("5", 246000), ("5", 156000), ("5", True),
    ("6", None), ("6", True), ("6", Decimal("1.1")), ("6", 10**24),
    ("11", Decimal("NaN")), ("11", Decimal("-0.1")), ("11", Decimal("0.12345678901")),
    ("13", -1), ("13", Decimal("1.1")), ("14", float("inf")),
    ("21", True), ("21", 0), ("21", 1000001),
])
def test_invalid_fields(field, value):
    body = response(total=1)
    body["data"][0][field] = value
    with pytest.raises(ValueError):
        parsed(body)


def test_missing_fields_unknown_shape_and_money_sum():
    body = response(total=1)
    del body["data"][0]["7"]
    with pytest.raises(ValueError, match="字段"):
        parsed(body)
    body = response(total=1)
    body["data"][0]["future"] = 1
    with pytest.raises(ValueError, match="结构"):
        parsed(body)
    body = response(total=1)
    body["data"][0]["8"] += 1
    with pytest.raises(ValueError, match="合计"):
        parsed(body)


def test_zero_and_negative_values_are_not_missing():
    body = response(total=1)
    row = body["data"][0]
    row.update({"6": -100, "7": 100, "8": 0, "11": 0, "14": 0, "5": 0})
    result = parsed(body).rows[0]
    assert result[2:6] == ["-100", "100", "0", "0"]
    assert result[7:9] == ["0", "000000"]


def test_decode_preserves_decimal_and_rejects_duplicate_json_keys():
    body = response(total=1)
    body["data"][0]["11"] = 0.12712
    body["data"][0]["14"] = -0.09572
    raw = json.dumps(body).encode()
    assert decode(raw, requested="2026-11-02", through="2026-11-03").rows[0][5] == "0.12712"
    with pytest.raises(ValueError, match="JSON字段重复"):
        decode(raw.replace(b'"errid": 0', b'"errid": 0, "errid": 0'),
               through="2026-11-03")


def test_normalization_precision_and_complete_set_validation():
    assert number(Decimal("-0.00"), scale=2) == "0"
    assert number(10**24 - 1) == "999999999999999999999999"
    with pytest.raises(ValueError):
        number(0.1, scale=10)
    rows = DayAssembly(parsed(response(total=2))).finish()
    with pytest.raises(ValueError):
        validate([rows[0], rows[0]])
    with pytest.raises(ValueError):
        validate(list(reversed(rows)))


def test_lifecycle_plan_uses_calendar_and_sql_coverage():
    days = ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29", "2026-10-30"]
    assert plan(days, set()) == days
    assert plan(days, set(days)) == days[-3:]
    assert plan(days, set(days) - {days[0]}) == [days[0], *days[-3:]]
    assert plan(days, set(days), force=True) == days
    assert plan(days + ["2026-11-02"], set(days)) == [*days[-2:], "2026-11-02"]
    # A lost Redis checkpoint cannot expand scope when SQL coverage survives.
    assert plan(days, set(days)) == days[-3:]
    with pytest.raises(ValueError):
        plan(days + [days[0]], set())
