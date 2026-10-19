"""Typed daily index prices; source identities stay distinct from stock codes."""

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from empire.contracts.security import index_code

PROJECT = "ths-index-prices"
JOB = PROJECT + "-v1"
BASE = "https://d.10jqka.com.cn/v4/line/"
FIELDS = ("open", "high", "low", "close", "volume", "amount")


def url(code, unit="last"):
    index_code(code)
    if unit != "last" and (not str(unit).isdigit() or not 1990 <= int(unit) <= 2100):
        raise ValueError("指数行情年份无效")
    return f"{BASE}zs_{code}/01/{unit}.js"


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("指数行情日期格式无效")
    date.fromisoformat(value)
    return value


def number(value, price=False):
    if not isinstance(value, str) or not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        raise ValueError("指数行情数字格式无效")
    try:
        n = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("指数行情数字无效") from exc
    scale, integer = (6, 12) if price else (4, 20)
    if abs(n) >= Decimal(10) ** integer or (price and n <= 0):
        raise ValueError("指数行情数字越界")
    if n != n.quantize(Decimal(1).scaleb(-scale)):
        raise ValueError("指数行情精度越界")
    return "0" if n == 0 else format(n.normalize(), "f")


def volume_amount_valid(values):
    """Retain source amounts while separating financial quality from syntax."""
    return all(v is None or Decimal(v) >= 0 for v in values)


def price_relation_valid(values):
    """Check known source OHLC without guessing which contradictory value is wrong."""
    op, high, low, close = [Decimal(v) if v is not None else None for v in values]
    return not (
        high is not None and low is not None and low > high
        or low is not None and any(v is not None and v < low for v in (op, close))
        or high is not None and any(v is not None and v > high for v in (op, close))
    )


def validate_rows(rows, year=None):
    if not isinstance(rows, list) or not 1 <= len(rows) <= (366 if year else 1000):
        raise ValueError("指数行情行数无效")
    last = ""
    for row in rows:
        if not isinstance(row, list) or len(row) != 7:
            raise ValueError("指数行情字段不完整")
        d = day(row[0])
        if d <= last or (year is not None and int(d[:4]) != year):
            raise ValueError("指数行情重复、乱序或跨年")
        if any(number(v, i < 4) != v for i, v in enumerate(row[1:])
               if not ((i < 3 or i == 5) and v is None)):
            raise ValueError("指数行情数字未规范化")
        last = d
