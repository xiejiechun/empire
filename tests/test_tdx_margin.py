import copy

import pytest

from empire.features.margin.contract import pack, unpack
from empire.features.margin.source import COLUMNS, params, parse


def response():
    return {
        "ErrorCode": 0,
        "ResultSets": [
            {
                "ColName": COLUMNS,
                "Count": 2,
                "Content": [
                    [100, 1000, 10, "20261028", 200, 20, 5, 1],
                    [90, 900, 9, "20261027", 190, 30, 4, 2],
                ],
            },
            {"ColName": ["page"], "Count": 1, "Content": [[1]]},
            {"ColName": ["count"], "Count": 1, "Content": [[2]]},
        ],
    }


def test_exact_10000_and_decimal_roundtrip():
    assert params("688256.SH") == ["2", "1", "688256", "", "1", "1", "10000"]
    rows = parse(response(), "2026-10-30")
    assert rows[0] == ["2026-10-28", "100", "1000", "10", "200", "20", "5", "1"]
    assert unpack(pack(rows)) == rows


@pytest.mark.parametrize(
    "kind",
    ["duplicate", "total", "page", "count", "columns", "negative", "null", "future", "precision"],
)
def test_invalid_complete_response(kind):
    body = copy.deepcopy(response())
    rows = body["ResultSets"][0]["Content"]
    if kind == "duplicate":
        rows[1] = rows[0][:]
    elif kind == "total":
        body["ResultSets"][2]["Content"] = [[3]]
    elif kind == "page":
        body["ResultSets"][1]["Content"] = [[2]]
    elif kind == "count":
        body["ResultSets"][0]["Count"] = 1
    elif kind == "columns":
        body["ResultSets"][0]["ColName"] = COLUMNS[::-1]
    elif kind == "negative":
        rows[0][0] = -1
    elif kind == "null":
        rows[0][4] = None
    elif kind == "future":
        rows[0][3] = "20261101"
    elif kind == "precision":
        rows[0][0] = "1.000000001"
    with pytest.raises(ValueError):
        parse(body, "2026-10-30")


def test_valid_empty_requires_count_proof():
    body = response()
    body["ResultSets"][0].update(Content=[], Count=0)
    body["ResultSets"][2]["Content"] = [[0]]
    assert parse(body, "2026-10-30") == []
    body["ResultSets"].pop()
    with pytest.raises(ValueError):
        parse(body, "2026-10-30")


def test_source_suspension_can_lack_market_context_without_losing_margin_facts():
    body = response()
    body["ResultSets"][0]["Content"][0][:3] = [None, None, None]
    rows = parse(body, "2026-10-30")
    assert rows[0][1:4] == [None, None, None]
    assert rows[0][4:] == ["200", "20", "5", "1"]
