"""Canonical daily industry facts and bounded maintenance planning."""

import hashlib
import json
import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

PROJECT, JOB, DATASET = "tdx-industry-margin", "tdx-industry-margin-v1", "industry_margin.tdx_day"
CONTRACT = 1
START = "2016-01-01"
TABLES = ("industry_margin_day", "industry_margin_daily")
FIELDS = (
    "lending_balance",
    "financing_balance",
    "financing_buy",
    "financing_repay",
    "lending_sell",
    "lending_repay",
    "lending_volume",
)


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("行业融资融券日期格式无效")
    parsed = date.fromisoformat(value)
    if not 2016 <= parsed.year <= 2200:
        raise ValueError("行业融资融券日期超出声明范围")
    return value


def number(value):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        raise ValueError("行业融资融券数值类型无效")
    try:
        n = Decimal(str(value))
        if not n.is_finite() or abs(n) >= Decimal(10) ** 20:
            raise ValueError("行业融资融券数值超界")
        if n != n.quantize(Decimal("0.00000001")):
            raise ValueError("行业融资融券精度超过8位")
    except InvalidOperation:
        raise ValueError("行业融资融券数值无效") from None
    value = format(n, "f")
    return "0" if not n else value.rstrip("0").rstrip(".") if "." in value else value


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def validate(rows):
    if not isinstance(rows, list) or len(rows) > 256:
        raise ValueError("行业融资融券完整日期集合超限")
    for row in rows:
        if not isinstance(row, list) or len(row) != 8:
            raise ValueError("行业融资融券记录结构无效")
        if (
            not isinstance(row[0], str)
            or not row[0].strip()
            or row[0] != row[0].strip()
            or len(row[0]) > 64
            or "\x00" in row[0]
        ):
            raise ValueError("行业名称缺失或超限")
        if any(number(v) != v for v in row[1:]):
            raise ValueError("行业融资融券数值非规范格式")
    names = [r[0] for r in rows]
    if names != sorted(set(names)):
        raise ValueError("行业集合重复或非规范顺序，不能以去重掩盖遗漏")
    return rows


def dates(start, end):
    first, last = date.fromisoformat(day(start)), date.fromisoformat(day(end))
    if first > last:
        raise ValueError("行业融资融券起止日期倒置")
    return [(first + timedelta(days=i)).isoformat() for i in range((last - first).days + 1)]


def plan(start, end, existing, through, *, force=False):
    current = date.fromisoformat(day(through))
    return [
        d
        for d in dates(start, end)
        if force
        or d not in existing
        or (date.fromisoformat(end) - date.fromisoformat(d)).days < 7
        or date.fromisoformat(d).toordinal() % 90 == current.toordinal() % 90
    ]
