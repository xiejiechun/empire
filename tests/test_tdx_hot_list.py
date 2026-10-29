"""Source semantics include actual Shanghai/Shenzhen and old-source shapes."""

import copy
from decimal import Decimal

import pytest

from empire.features.hot_list.contract import number, validate_dates
from empire.features.hot_list.presentation import render, summary
from empire.features.hot_list.source import (
    DETAIL_COLUMNS,
    DIRECTORY_COLUMNS,
    params,
    parse_detail,
    parse_directory,
)

CODE, DATE = "601139.SH", "2026-03-03"


def directory(dates=None, code=CODE):
    rows = [[d, 2, code[:6]] for d in (dates if dates is not None else [DATE])]
    return dict(
        ErrorCode=0, ResultSets=[dict(ColName=DIRECTORY_COLUMNS, Count=len(rows), Content=rows)]
    )


def detail(*, empty=False, revised=False, shenzhen=False):
    data = [
        [["070001", "涨幅偏离值达7%的证券", 100, 1000, 7.87, 10.07]],
        [
            [
                1,
                "070001",
                "机构专用",
                30 if revised else 20,
                None,
                30 if revised else 20,
                "涨幅偏离值达7%的证券",
                "B",
                1000,
                100,
                0,
                0,
                None,
                None,
                None,
                None,
            ],
            [
                1,
                "070001",
                "机构专用",
                None,
                10,
                -10,
                "涨幅偏离值达7%的证券",
                "S",
                1000,
                100,
                0,
                0,
                None,
                None,
                None,
                None,
            ],
        ],
        [["机构专用", 4553]],
        [[2127]],
        [],
    ]
    if empty:
        data[1] = []
    if shenzhen:
        data[1][0][3:6] = [20, 10, 10]
        data[1][1][3:6] = [20, 10, 10]
        data[1].append(
            [
                2,
                "070001",
                "机构专用",
                2,
                9,
                -7,
                "涨幅偏离值达7%的证券",
                "S",
                1000,
                100,
                0,
                0,
                "标签",
                None,
                None,
                None,
            ]
        )
    return dict(
        ErrorCode=0,
        ResultSets=[
            dict(ColName=cols, Count=len(rows), Content=rows)
            for cols, rows in zip(DETAIL_COLUMNS, data, strict=True)
        ],
    )


def test_protocol_directory_and_null_zero_precision():
    assert params(CODE) == ["0", "601139", ""]
    assert params(CODE, DATE) == ["1", "601139", DATE]
    assert parse_directory(directory(), CODE, DATE) == [DATE]
    value = parse_detail(detail())
    assert value["status"] == "present"
    assert value["seats"][0]["sell_amount"] is None
    assert number(Decimal("1000.00000000")) == "1000"
    assert number(0) == "0"
    assert parse_detail(detail(empty=True))["status"] == "source_empty"
    assert parse_detail(detail(shenzhen=True))["seats"][2]["seat_name"] == "机构专用"


@pytest.mark.parametrize(
    "change", ["count", "duplicate", "missing_reason", "amount", "column", "error"]
)
def test_business_validation_does_not_dedup_away_errors(change):
    body = detail()
    if change == "count":
        body["ResultSets"][1]["Count"] += 1
    if change == "duplicate":
        body["ResultSets"][1]["Content"][1] = copy.deepcopy(body["ResultSets"][1]["Content"][0])
    if change == "missing_reason":
        body["ResultSets"][1]["Content"][0][1] = "missing"
    if change == "amount":
        body["ResultSets"][1]["Content"][0][3] = Decimal("1.000000001")
    if change == "column":
        body["ResultSets"][2]["ColName"] = ["unknown"]
    if change == "error":
        body["ErrorCode"] = -1005
    with pytest.raises(ValueError):
        parse_detail(body)


def test_duplicate_date_different_set_and_future_rejected():
    for dates in ([DATE, DATE], ["2020-01-01", DATE], ["2026-03-04"]):
        with pytest.raises(ValueError):
            parse_directory(directory(dates), CODE, DATE)
    with pytest.raises(ValueError):
        parse_directory(directory(code="000001.SZ"), CODE, DATE)
    validate_dates([], DATE)


def test_old_repeated_reason_rows_without_seats_preserved():
    body = detail(empty=True)
    body["ResultSets"][0]["Content"] *= 5
    body["ResultSets"][0]["Count"] = 5
    value = parse_detail(body)
    assert len(value["reasons"]) == 5 and value["status"] == "source_empty"


def variant_detail():
    # 600198.SH/2024-09-25: buy/sell rows match different exact summaries.
    body = detail()
    reasons, seats = body["ResultSets"][:2]
    reasons["Content"][0][2:4] = [24732.9432, 223819.32]
    variant = copy.deepcopy(reasons["Content"][0])
    variant[3] = 223819.3174
    reasons["Content"].append(variant)
    reasons["Count"] = 2
    for row, turnover in zip(seats["Content"], (223819.32, 223819.3174), strict=True):
        row[8:10] = [turnover, 24732.9432]
    return body


def test_reason_variants_match_whole_summary_and_preserve_precision():
    body = variant_detail()
    value = parse_detail(body)
    assert value["status"] == "partial"
    assert {r["turnover"] for r in value["reasons"]} == {"223819.32", "223819.3174"}
    assert len(value["seats"]) == 2
    for result in body["ResultSets"][:2]:
        result["Content"].reverse()
    assert parse_detail(body) == value


@pytest.mark.parametrize("field,value", [(8, 223819.3), (9, 24732.9), (6, "其他原因")])
def test_reason_variant_seat_must_match_one_complete_header(field, value):
    body = variant_detail()
    body["ResultSets"][1]["Content"][0][field] = value
    with pytest.raises(ValueError, match="席位与原因"):
        parse_detail(body)


def test_reason_variant_cannot_mix_fields_from_different_headers():
    body = variant_detail()
    body["ResultSets"][0]["Content"][1][2] = 999
    with pytest.raises(ValueError, match="席位与原因"):
        parse_detail(body)


def test_000063_tied_sell_rank_preserves_both_seats_and_stable_order():
    # 2018-06-22: two different sellers each disclose 1498万元 at rank 1.
    body = detail()
    seats = body["ResultSets"][1]
    seller = seats["Content"][1]
    seller[3:6] = [0, 1498, -1498]
    tied = copy.deepcopy(seller)
    tied[2] = "中国国际金融股份有限公司上海分公司"
    seats["Content"].append(tied)
    seats["Count"] = 3
    value = parse_detail(body)
    assert value["status"] == "present"
    sellers = [r for r in value["seats"] if r["side"] == "S"]
    assert [(r["seat_rank"], r["sell_amount"]) for r in sellers] == [(1, "1498")] * 2
    assert {r["seat_name"] for r in sellers} == {"机构专用", tied[2]}
    seats["Content"].reverse()
    assert parse_detail(body) == value
    # Same count with one seller replacing the other must still fail.
    seats["Content"][1] = copy.deepcopy(seats["Content"][0])
    with pytest.raises(ValueError, match="完整席位集合重复"):
        parse_detail(body)


def test_display_cross_list_total_does_not_drop_distinct_institutions():
    value = parse_detail(detail(shenzhen=True))
    assert summary(value, "070001") == (Decimal(22), Decimal(19))
    value.update(
        unified_code=CODE,
        list_date=DATE,
        detail_status=value.pop("status"),
        version_observed_at="2026-03-03 19:30:00",
    )
    output = render(value)
    assert "机构专用" in output and "查询时刻" in output and "来源缺" not in output


def test_daily_default():
    from empire.features.hot_list.bundle import bundle

    task = bundle({"redis": {}}).tasks[0].value
    assert task.default_schedule.mode == "daily" and task.default_schedule.daily_time == "19:30"
    assert task.parallel_downloads


def test_identical_same_direction_institutions_are_not_collapsed():
    value = parse_detail(detail(shenzhen=True))
    row = copy.deepcopy(value["seats"][-1])
    row["seat_rank"] += 1
    value["seats"].append(row)
    before = summary(dict(seats=value["seats"][:-1]), "070001")
    after = summary(value, "070001")
    assert after == (
        before[0] + Decimal(row["buy_amount"] or "0"),
        before[1] + Decimal(row["sell_amount"] or "0"),
    )
