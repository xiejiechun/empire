"""ETF facts use precise numbers; source absence is never a zero value."""

import re
from datetime import date, datetime

from empire.core.time import CHINA
from empire.features.yuanhang_etf.contract import day, number, security
from empire.features.yuanhang_etf.contract import digest as digest

CONTRACT = 1
START = "2004-12-30"
SHARE_DATASET, NAV_DATASET = "etf.share.day", "etf.nav.range"
PROJECTS = ("sse-etf-shares", "szse-etf-shares", "ttjj-etf-nav")
SOURCES = dict(zip(PROJECTS, ("sse", "szse", "ttjj"), strict=True))
SHARE_FIELDS = ("name", "total_shares", "source_group", "source_type")
NAV_FIELDS = (
    "value_kind",
    "unit_nav",
    "accumulated_nav",
    "daily_change_pct",
    "income_value",
    "income_basis_shares",
    "yield_7d_pct",
    "currency",
    "purchase_status",
    "redemption_status",
    "distribution_text",
    "fund_type",
    "income_label",
    "nav_type",
    "income_start_date",
    "actual_income",
    "dividend_value",
    "dividend_per_ten",
    "dividend_basis",
    "distribution_type",
)
NUMERIC = frozenset(
    (
        "unit_nav",
        "accumulated_nav",
        "daily_change_pct",
        "income_value",
        "income_basis_shares",
        "yield_7d_pct",
        "actual_income",
        "dividend_value",
        "dividend_per_ten",
    )
)
TEXT_LIMITS = dict(
    value_kind=16,
    currency=3,
    purchase_status=64,
    redemption_status=64,
    distribution_text=1024,
    fund_type=16,
    income_label=64,
    nav_type=16,
    dividend_basis=64,
    distribution_type=64,
)
TABLES = ("etf_daily_share", "etf_share_day", "etf_daily_nav", "etf_nav_year")
MAX_ROWS, MAX_BYTES = 5000, 2 * 1024 * 1024


def bounded_text(value, maximum, *, required=False):
    if value is None or value == "":
        if required:
            raise ValueError("ETF必需文本为空")
        return None
    if not isinstance(value, str) or len(value) > maximum or "\x00" in value:
        raise ValueError("ETF文本类型或长度超限")
    return value


def validate_share(rows, source):
    if source not in ("sse", "szse") or not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise ValueError("ETF份额来源或完整日上限无效")
    previous = ""
    for r in rows:
        if not isinstance(r, list) or len(r) != 5:
            raise ValueError("ETF份额字段无效")
        code = security(r[0])
        if code <= previous or not code.endswith(".SH" if source == "sse" else ".SZ"):
            raise ValueError("ETF份额代码集合重复、乱序或来源市场不符")
        bounded_text(r[1], 128, required=True)
        if number(r[2]) != r[2] or r[2] is None or r[2].startswith("-"):
            raise ValueError("ETF总份额必须为非负精确数值")
        if r[3] not in ("etf", "money") or source == "szse" and r[3] != "etf":
            raise ValueError("ETF来源分类无效")
        bounded_text(r[4], 64)
        previous = code
    return rows


def validate_nav(rows, first, last):
    day(first), day(last)
    if first > last or first[:4] != last[:4] or not isinstance(rows, list) or len(rows) > 366:
        raise ValueError("ETF净值年度范围无效")
    previous = ""
    for row in rows:
        if not isinstance(row, list) or len(row) != len(NAV_FIELDS) + 1:
            raise ValueError("ETF净值字段集合无效")
        stamp = day(row[0])
        if not first <= stamp <= last or stamp <= previous:
            raise ValueError("ETF净值日期重复、乱序或越界")
        values = dict(zip(NAV_FIELDS, row[1:], strict=True))
        if values["value_kind"] not in ("nav", "income"):
            raise ValueError("ETF净值指标类型无效")
        for name, value in values.items():
            if name in NUMERIC:
                if number(value) != value:
                    raise ValueError("ETF净值数值不是规范精确值")
            elif name == "income_start_date":
                if value is not None and day(value) > stamp:
                    raise ValueError("ETF收益起点晚于披露日期")
            else:
                bounded_text(value, TEXT_LIMITS[name])
        for field in ("unit_nav", "accumulated_nav", "income_basis_shares"):
            if values[field] is not None and values[field].startswith("-"):
                raise ValueError("ETF净值或份额基数为负")
        if values["income_basis_shares"] == "0":
            raise ValueError("ETF收益份额基数必须大于0")
        if values["currency"] is not None and not re.fullmatch("[A-Z]{3}", values["currency"]):
            raise ValueError("ETF币种代码无效")
        if values["value_kind"] == "income" and any(
            values[k] is not None for k in ("unit_nav", "accumulated_nav")
        ):
            raise ValueError("收益口径不能冒充单位净值")
        if values["value_kind"] == "nav" and any(
            values[k] is not None for k in ("income_value", "yield_7d_pct", "income_basis_shares")
        ):
            raise ValueError("净值口径不能混入收益口径")
        previous = stamp
    return rows


def years(first, last):
    day(first), day(last)
    if first > last or not START <= first <= last <= datetime.now(CHINA).date().isoformat():
        raise ValueError("ETF来源请求范围无效")
    return [
        (max(first, f"{y}-01-01"), min(last, f"{y}-12-31"))
        for y in range(int(first[:4]), int(last[:4]) + 1)
    ]


def coverage_through(segments, year):
    from datetime import timedelta

    from empire.sources.yuanhang_ranges import validated_segments

    expected = date.fromisoformat(max(START, f"{year}-01-01"))
    last = None
    for first, end, _ in validated_segments(segments, year):
        if first > expected:
            break
        last, expected = end.isoformat(), end + timedelta(days=1)
    return last
