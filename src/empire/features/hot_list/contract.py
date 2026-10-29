"""Bounded canonical business facts; source ranks are not seat identities."""

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from empire.contracts.security import split_unified_code

PROJECT, JOB, DATASET = "tdx-hot-list", "tdx-hot-list-v1", "hot_list.tdx_unit"
CONTRACT = 1
TABLES = ("hot_list_day", "hot_list_reason", "hot_list_seat")
REASONS = ("seq", "reason_code", "reason", "volume", "turnover", "close_price", "change_pct")
SEATS = (
    "seq",
    "reason_code",
    "side",
    "seat_rank",
    "seat_name",
    "buy_amount",
    "sell_amount",
    "net_amount",
    "extension",
)


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def security(value):
    split_unified_code(value)
    return value


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("龙虎榜日期格式无效")
    parsed = date.fromisoformat(value)
    if not 1990 <= parsed.year <= 2200:
        raise ValueError("龙虎榜日期范围无效")
    return value


def number(value, *, pct=False):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("龙虎榜数值类型无效")
    try:
        n = Decimal(str(value))
        if not n.is_finite() or abs(n) >= Decimal(10) ** (12 if pct else 20):
            raise ValueError("龙虎榜数值超界")
        if n != n.quantize(Decimal("0.00000001")):
            raise ValueError("龙虎榜数值精度超过8位；不截断")
    except InvalidOperation:
        raise ValueError("龙虎榜数值无效") from None
    return (
        "0"
        if not n
        else format(n, "f").rstrip("0").rstrip(".")
        if "." in format(n, "f")
        else str(n)
    )


def text_value(value, maximum, *, optional=False):
    if optional and value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or "\x00" in value:
        raise ValueError("龙虎榜文本缺失或超限")
    return value


def validate_dates(values, through):
    day(through)
    if not isinstance(values, list) or len(values) > 20000:
        raise ValueError("龙虎榜日期目录超限")
    for value in values:
        if day(value) > through:
            raise ValueError("龙虎榜目录含未来日期")
    if values != sorted(set(values), reverse=True):
        raise ValueError("龙虎榜目录重复或乱序，不能以去重掩盖遗漏")


def validate_detail(value):
    if not isinstance(value, dict) or set(value) != {"reasons", "seats", "auxiliary", "status"}:
        raise ValueError("龙虎榜详情契约错误")
    reasons, seats, auxiliary = value["reasons"], value["seats"], value["auxiliary"]
    if (
        not isinstance(reasons, list)
        or len(reasons) > 1000
        or not isinstance(seats, list)
        or len(seats) > 10000
    ):
        raise ValueError("龙虎榜完整日期超限")
    for rows, columns in ((reasons, REASONS), (seats, SEATS)):
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict) or set(row) != set(columns) or row["seq"] != index:
                raise ValueError("龙虎榜来源序号或字段不符")
            text_value(row["reason_code"], 32)
    for row in reasons:
        text_value(row["reason"], 1000)
        for key in ("volume", "turnover", "close_price", "change_pct"):
            if row[key] != number(row[key], pct=key == "change_pct"):
                raise ValueError("龙虎榜原因数值非规范格式")
            if key != "change_pct" and row[key] is not None and Decimal(row[key]) < 0:
                raise ValueError("龙虎榜量价金额不能为负")
    keys = []
    for row in seats:
        if (
            row["side"] not in ("B", "S")
            or type(row["seat_rank"]) is not int
            or not 1 <= row["seat_rank"] <= 1000
        ):
            raise ValueError("龙虎榜方向或排名无效")
        text_value(row["seat_name"], 256)
        # Source ranks can tie. Only the complete canonical seat identifies a
        # duplicate; seq identifies its position in the complete response.
        keys.append(digest({k: v for k, v in row.items() if k != "seq"}))
        for key in ("buy_amount", "sell_amount", "net_amount"):
            if row[key] != number(row[key]):
                raise ValueError("龙虎榜席位金额非规范格式")
            if key != "net_amount" and row[key] is not None and Decimal(row[key]) < 0:
                raise ValueError("龙虎榜买卖金额不能为负")
        ext = row["extension"]
        if (
            not isinstance(ext, dict)
            or set(ext) != {"schema", "bq1", "bq2", "bq3", "bq4", "yxyz", "gsd"}
            or ext["schema"] != 1
        ):
            raise ValueError("龙虎榜扩展字段错误")
        for k in ("bq1", "bq2", "bq3", "bq4"):
            text_value(ext[k], 128, optional=True)
        if any(type(ext[k]) is not int or not 0 <= ext[k] <= 2147483647 for k in ("yxyz", "gsd")):
            raise ValueError("龙虎榜未公开标记类型改变")
        if len(json.dumps(ext, ensure_ascii=False).encode()) > 4096:
            raise ValueError("龙虎榜席位扩展超限")
    if len(keys) != len(set(keys)):
        raise ValueError("龙虎榜完整席位集合重复，不能以去重掩盖遗漏")
    reason_keys = {r["reason_code"] for r in reasons}
    if not {r["reason_code"] for r in seats} <= reason_keys:
        raise ValueError("龙虎榜席位缺少原因关联")
    expected = (
        "source_empty"
        if not seats
        else "present"
        if reason_keys == {r["reason_code"] for r in seats} and len(reason_keys) == len(reasons)
        else "partial"
    )
    if value["status"] != expected:
        raise ValueError("龙虎榜可用性状态与来源集合不符")
    if (
        not isinstance(auxiliary, dict)
        or set(auxiliary) != {"schema", "counts", "institution_count", "related"}
        or auxiliary["schema"] != 1
    ):
        raise ValueError("龙虎榜辅助信息契约错误")
    if len(json.dumps(auxiliary, ensure_ascii=False).encode()) > 65536:
        raise ValueError("龙虎榜辅助信息超限")
    if any(
        not isinstance(auxiliary[k], list) or len(auxiliary[k]) > 500 for k in ("counts", "related")
    ):
        raise ValueError("龙虎榜辅助集合超限")
    n = auxiliary["institution_count"]
    if n is not None and (type(n) is not int or not 0 <= n <= 2147483647):
        raise ValueError("龙虎榜机构次数无效")
    for name, count in auxiliary["counts"]:
        text_value(name, 256)
        if type(count) is not int or not 0 <= count <= 2147483647:
            raise ValueError("龙虎榜活动次数无效")
    for r in auxiliary["related"]:
        if not isinstance(r, list) or len(r) != 7:
            raise ValueError("龙虎榜关联标签结构错误")
        day(r[0])
        if not isinstance(r[1], str) or not re.fullmatch(r"\d{6}", r[1]):
            raise ValueError("龙虎榜关联证券代码无效")
        text_value(r[2], 32)
        text_value(r[3], 256)
        if r[4] not in ("B", "S") or type(r[5]) is not int or not 1 <= r[5] <= 1000:
            raise ValueError("龙虎榜关联标签方向/排名无效")
        text_value(r[6], 128)
    return value
