"""Exact, bounded daily source facts; no dependency on another business feature."""

import hashlib
import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

from empire.contracts.security import split_unified_code

PROJECT = "eastmoney-graymarket"
JOB = "eastmoney-graymarket-v1"
DATASET = "graymarket.eastmoney_day"
CONTRACT = 1
START = "2026-05-11"
PAGE_SIZE = 100
MAX_ROWS = 10000
MAX_DAY_BYTES = 4 * 1024 * 1024
TABLES = ("graymarket_day", "graymarket_daily")
FIELDS = (
    "name",
    "dark_flow",
    "visible_flow",
    "main_flow",
    "dark_activity",
    "price",
    "change_ratio",
    "source_time",
    "source_rank",
)


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("资金榜日期格式无效")
    parsed = date.fromisoformat(value)
    if not 1990 <= parsed.year <= 2200:
        raise ValueError("资金榜日期超界")
    return value


def number(value, *, scale=0, integer_digits=24):
    # Source JSON is decoded with Decimal; floats from callers are rejected so
    # binary rounding never silently becomes an accepted business fact.
    if isinstance(value, bool) or not isinstance(value, (int, str, Decimal)):
        raise ValueError("资金榜数值类型无效或缺失")
    try:
        n = Decimal(value)
        with localcontext() as context:
            context.prec = 64
            if (
                not n.is_finite()
                or abs(n) >= Decimal(10) ** integer_digits
                or n != n.quantize(Decimal(1).scaleb(-scale))
            ):
                raise ValueError("资金榜数值范围或精度无效")
    except (InvalidOperation, ValueError):
        raise ValueError("资金榜数值范围或精度无效") from None
    text = format(n, "f")
    return "0" if n == 0 else text.rstrip("0").rstrip(".") if "." in text else text


def source_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{6}", value):
        raise ValueError("资金榜来源时间无效")
    if int(value[:2]) > 23 or int(value[2:4]) > 59 or int(value[4:]) > 59:
        raise ValueError("资金榜来源时间无效")
    return value


def validate_row(row):
    if not isinstance(row, list) or len(row) != 10:
        raise ValueError("资金榜规范行结构无效")
    split_unified_code(row[0])
    if (
        not isinstance(row[1], str)
        or not row[1].strip()
        or row[1] != row[1].strip()
        or len(row[1]) > 64
        or any(ord(c) < 32 for c in row[1])
    ):
        raise ValueError("资金榜证券名称缺失或超限")
    for i in (2, 3, 4):
        if number(row[i]) != row[i]:
            raise ValueError("资金榜金额不是规范十进制")
    for i in (5, 7):
        if number(row[i], scale=10, integer_digits=10) != row[i]:
            raise ValueError("资金榜比例不是规范十进制")
    if number(row[6], scale=3, integer_digits=15) != row[6] or Decimal(row[6]) < 0:
        raise ValueError("资金榜价格无效")
    if Decimal(row[5]) < 0:
        raise ValueError("资金榜活跃度不能为负")
    if Decimal(row[2]) + Decimal(row[3]) != Decimal(row[4]):
        raise ValueError("资金榜明盘与暗盘合计不符")
    source_time(row[8])
    if type(row[9]) is not int or not 1 <= row[9] <= 1000000:
        raise ValueError("资金榜来源序号无效")
    return row


def validate(rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS:
        raise ValueError("资金榜完整日期为空或超限")
    for row in rows:
        validate_row(row)
    keys = [r[0] for r in rows]
    if keys != sorted(set(keys)):
        raise ValueError("资金榜证券重复或规范集合顺序错误")
    if len(json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode()) > MAX_DAY_BYTES:
        raise ValueError("资金榜完整日期字节超限")
    return rows


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def plan(trading_dates, existing, *, force=False):
    """Caller supplies authoritative trading dates, never generated weekdays."""
    if (
        not isinstance(trading_dates, list)
        or len(trading_dates) > 60000
        or trading_dates != sorted(set(trading_dates))
    ):
        raise ValueError("资金榜交易日计划无效")
    for stamp in trading_dates:
        day(stamp)
    recent = set(trading_dates[-3:])
    return [d for d in trading_dates if force or d not in existing or d in recent]
