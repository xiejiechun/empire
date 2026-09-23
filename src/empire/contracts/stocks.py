"""Project-wide equity identifiers, independent of source and storage plugins."""

import re

MARKETS = {"sh": "SH", "sz": "SZ", "bj": "BJ"}
MARKET_NAMES = {"SH": "上海", "SZ": "深圳", "BJ": "北京"}


def normalize_sina_stock(row: dict) -> dict:
    if not isinstance(row, dict):
        raise ValueError("股票记录必须是对象")
    code, symbol, name = row.get("code"), row.get("symbol"), row.get("name")
    if not isinstance(code, str) or not re.fullmatch(r"[0-9]{6}", code):
        raise ValueError("股票代码必须是保留前导零的六位字符串")
    if not isinstance(symbol, str) or not re.fullmatch(r"(?:sh|sz|bj)[0-9]{6}", symbol):
        raise ValueError(f"不支持的新浪股票标识：{symbol!r}")
    if symbol[2:] != code:
        raise ValueError(f"新浪 symbol 与 code 不一致：{symbol} / {code}")
    if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
        raise ValueError("股票名称为空或超出长度限制")
    market = MARKETS[symbol[:2]]
    return {"code": code, "name": name.strip(), "unified_code": f"{code}.{market}",
            "market": market, "source_symbol": symbol}
