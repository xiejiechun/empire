"""Exact decimal source facts and a bounded complete-security message."""

import base64
import hashlib
import json
import re
import zlib
from datetime import date
from decimal import Decimal, InvalidOperation

from empire.contracts.security import split_unified_code

PROJECT, JOB, DATASET = "tdx-margin", "tdx-margin-v1", "margin.tdx_security"
CONTRACT, CAPACITY = 1, 10000
TABLES = ("margin_security", "margin_daily")
FIELDS = (
    "market_volume",
    "market_turnover",
    "close_price",
    "financing_balance",
    "financing_buy",
    "lending_balance",
    "lending_sell",
)


def security(value):
    split_unified_code(value)
    return value


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("融资融券日期格式无效")
    parsed = date.fromisoformat(value)
    if not 1990 <= parsed.year <= 2200:
        raise ValueError("融资融券日期超界")
    return value


def number(value, *, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("融资融券数值缺失或类型无效")
    try:
        n = Decimal(str(value))
        if (
            not n.is_finite()
            or not 0 <= n < Decimal("1e20")
            or n != n.quantize(Decimal(".00000001"))
        ):
            raise ValueError("融资融券数值范围或精度无效")
    except InvalidOperation:
        raise ValueError("融资融券数值无效") from None
    return format(n.normalize(), "f") if n else "0"


def validate(rows, through):
    day(through)
    if not isinstance(rows, list) or len(rows) > CAPACITY:
        raise ValueError("融资融券历史超出10000条上限")
    previous = None
    for row in rows:
        if not isinstance(row, list) or len(row) != 8:
            raise ValueError("融资融券行结构无效")
        stamp = day(row[0])
        if stamp > through or previous is not None and stamp >= previous:
            raise ValueError("融资融券日期重复、乱序或超出本轮范围")
        if any(number(v, optional=i < 3) != v for i, v in enumerate(row[1:])):
            raise ValueError("融资融券数值不是规范十进制")
        previous = stamp
    return rows


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def pack(rows):
    raw = json.dumps(rows, separators=(",", ":")).encode()
    if len(raw) > 4 * 1024**2:
        raise ValueError("融资融券完整证券消息超限")
    return dict(
        codec="zlib-json-v1", size=len(raw), body=base64.b64encode(zlib.compress(raw)).decode()
    )


def unpack(value):
    if (
        not isinstance(value, dict)
        or set(value) != {"codec", "size", "body"}
        or value["codec"] != "zlib-json-v1"
        or type(value["size"]) is not int
        or not 0 <= value["size"] <= 4 * 1024**2
        or not isinstance(value["body"], str)
        or len(value["body"]) > 500000
    ):
        raise ValueError("融资融券消息边界无效")
    decoder = zlib.decompressobj()
    try:
        raw = decoder.decompress(base64.b64decode(value["body"], validate=True), value["size"] + 1)
        if (
            len(raw) != value["size"]
            or not decoder.eof
            or decoder.unused_data
            or decoder.unconsumed_tail
        ):
            raise ValueError("融资融券压缩消息不完整")
        return json.loads(raw)
    except (ValueError, zlib.error) as exc:
        raise ValueError("融资融券消息损坏") from exc
