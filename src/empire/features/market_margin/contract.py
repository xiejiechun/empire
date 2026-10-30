"""Exact decimal source facts and a bounded complete-market message."""

import base64
import hashlib
import json
import re
import zlib
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext

PROJECT, JOB, DATASET = "ths-market-margin", "ths-market-margin-v1", "market_margin.ths_series"
CONTRACT, CAPACITY = 1, 10000
TABLES = ("market_margin_series", "market_margin_daily")
MARKETS = {"99": "沪深京合计", "3": "沪市", "2": "深市", "4": "京市"}
STARTS = {k: "2023-02-13" if k == "4" else "2010-03-31" for k in MARKETS}
FIELDS = (
    "financing_balance",
    "lending_balance",
    "financing_buy",
    "financing_net_buy",
    "lending_net_sell",
    "financing_net_change",
    "lending_net_change",
    "balance_ratio",
    "source_total",
)


def market(value):
    if value not in MARKETS:
        raise ValueError("市场编号无效")
    return value


def day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("融资融券日期格式无效")
    parsed = date.fromisoformat(value)
    if not 1990 <= parsed.year <= 2200:
        raise ValueError("融资融券日期超界")
    return value


def number(value, *, optional=False, ratio=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("融资融券数值缺失或类型无效")
    try:
        n = Decimal(str(value))
        with localcontext() as ctx:
            ctx.prec = 50
            exact = n == n.quantize(Decimal("1e-24" if ratio else "1e-8"))
        if not n.is_finite() or abs(n) >= Decimal("1e14" if ratio else "1e20") or not exact:
            raise ValueError("融资融券数值范围或精度无效")
    except InvalidOperation:
        raise ValueError("融资融券数值无效") from None
    value = format(n, "f")
    return "0" if not n else value.rstrip("0").rstrip(".") if "." in value else value


def validate(rows, through, code):
    market(code)
    day(through)
    if not isinstance(rows, list) or not rows or len(rows) > CAPACITY:
        raise ValueError("融资融券历史超出10000条上限")
    previous = None
    for row in rows:
        if not isinstance(row, list) or len(row) != 10:
            raise ValueError("融资融券行结构无效")
        stamp = day(row[0])
        if stamp > through or previous is not None and stamp <= previous:
            raise ValueError("融资融券日期重复、乱序或超出本轮范围")
        if any(number(v, optional=i >= 5, ratio=i == 7) != v for i, v in enumerate(row[1:])):
            raise ValueError("融资融券数值不是规范十进制")
        if any(Decimal(row[i]) < 0 for i in (1, 2, 3)):
            raise ValueError("融资融券余额/买入额不能为负")
        previous = stamp
    if rows[0][0] != STARTS[code]:
        raise ValueError("市场历史起点缺失或响应截断")
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
        raise ValueError("融资融券完整市场消息超限")
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
