"""Bounded wire encoding must preserve facts, never truncate large securities."""

import base64
import copy
import json
import zlib

import pytest

from empire.features.ths_capital.source import parse
from empire.features.ths_capital.transport import MAX_RAW, pack, unpack
from tests.test_ths_capital import STOCK, source


def facts():
    return parse(source().encode("gb18030"), STOCK)["rows"]


def test_large_complete_unit_roundtrip_and_deterministic_wire():
    rows = facts()
    for i in range(30):
        row = copy.deepcopy(rows["capital_project"][0])
        row["record_key"] = f"{i:064x}"
        row["project_name"] = str(i)
        row["description"] = "规范业务正文，不得截断。" * 700
        rows["capital_project"].append(row)
    assert len(json.dumps(rows, ensure_ascii=False).encode()) > 524288
    encoded = pack(rows)
    assert len(json.dumps(encoded).encode()) < 524288
    assert unpack(encoded) == rows
    assert pack(unpack(encoded)) == encoded


@pytest.mark.parametrize(
    "mutation",
    [
        "negative",
        "oversize",
        "short",
        "long",
        "truncated",
        "trailing",
        "base64",
        "columns",
        "tables",
        "count",
    ],
)
def test_malformed_or_oversized_transport_rejected(mutation):
    value = pack(facts())
    if mutation == "negative":
        value["bytes"] = -1
    elif mutation == "oversize":
        value["bytes"] = MAX_RAW + 1
    elif mutation == "short":
        value["bytes"] -= 1
    elif mutation == "long":
        value["bytes"] += 1
    elif mutation == "truncated":
        value["body"] = base64.b64encode(base64.b64decode(value["body"])[:-2]).decode()
    elif mutation == "trailing":
        value["body"] = base64.b64encode(base64.b64decode(value["body"]) + b"junk").decode()
    elif mutation == "base64":
        value["body"] = "!!!!"
    else:
        matrix = json.loads(zlib.decompress(base64.b64decode(value["body"])))
        if mutation == "columns":
            matrix["capital_project"][0].pop()
        elif mutation == "tables":
            matrix.pop("capital_project")
        elif mutation == "count":
            matrix["capital_project"] = [matrix["capital_project"][0]] * 10001
        raw = json.dumps(matrix).encode()
        value.update(bytes=len(raw), body=base64.b64encode(zlib.compress(raw)).decode())
    with pytest.raises(ValueError):
        unpack(value)


def test_legacy_uncompressed_rows_are_not_a_second_runtime_format():
    with pytest.raises(ValueError):
        unpack(facts())
