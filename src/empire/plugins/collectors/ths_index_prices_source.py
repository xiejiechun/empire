"""One last snapshot and independent annual responses, no all.js double read."""

import json
import re
from datetime import datetime, time

from empire.contracts.index_prices import FIELDS, day, number, validate_rows
from empire.contracts.indices import index_code
from empire.core.time import CHINA


def pending_today(row, today):
    """THS current-day placeholder; historical missing fields remain real source data."""
    return row[0] == today and row[1:4] == [None, None, None] and row[5:] == ["0", None]


def parse(source, code, unit):
    index_code(code)
    match = re.fullmatch(
        r"\s*quotebridge_v4_line_zs_"
        + re.escape(code)
        + "_01_"
        + str(unit)
        + r"\((\{.*\})\)\s*;?\s*",
        source,
        re.S,
    )
    if not match:
        raise ValueError("指数行情JSONP身份错误或响应截断")

    def unique(pairs):
        result = {}
        for k, v in pairs:
            if k in result:
                raise ValueError("指数行情JSON字段重复")
            result[k] = v
        return result

    data = json.loads(match[1], object_pairs_hook=unique)
    if not isinstance(data, dict) or not isinstance(data.get("data"), str) or not data["data"]:
        raise ValueError("指数行情响应缺少有效数据")
    rows = []
    raw = data["data"].split(";")
    if raw[-1] == "":
        raw.pop()
    for line in raw:
        cells = line.split(",")
        if len(cells) != 11 or not re.fullmatch(r"\d{8}", cells[0]):
            raise ValueError("指数行情来源字段或日期结构改变")
        date = day(f"{cells[0][:4]}-{cells[0][4:6]}-{cells[0][6:]}")
        values = []
        for i, value in enumerate(cells[1:7]):
            try:
                values.append(None if (i < 3 or i == 5) and value == "" else number(value, i < 4))
            except ValueError as exc:
                detail = dict(index_code=code, trade_date=date, field=FIELDS[i],
                              source_value=value[:80], source_value_truncated=len(value) > 80)
                error = ValueError(f"{exc}：{code} {date} {FIELDS[i]}={value[:80]!r}")
                error.source_metadata = detail
                raise error from exc
        rows.append([date, *values])
    validate_rows(rows, int(unit) if unit != "last" else None)
    return data, rows


def recent(source, code, now=None):
    now = (now or datetime.now(CHINA)).astimezone(CHINA)
    data, rows = parse(source, code, "last")
    years = data.get("year")
    if not isinstance(years, dict) or not 1 <= len(years) <= 40:
        raise ValueError("指数行情来源年份目录无效")
    counts = {}
    for year, count in years.items():
        if (
            not re.fullmatch(r"\d{4}", year)
            or not 1990 <= int(year) <= now.year
            or type(count) is not int
            or not 1 <= count <= 366
        ):
            raise ValueError("指数行情年份或条数越界")
        counts[year] = count
    if (
        not str(data.get("total", "")).isdigit()
        or sum(counts.values()) != int(data["total"])
        or type(data.get("num")) is not int
        or data["num"] != len(rows)
    ):
        raise ValueError("指数行情总数、年份数或近期条数不一致")
    first = data.get("start", "")
    if not isinstance(first, str) or not re.fullmatch(r"\d{8}", first):
        raise ValueError("指数行情来源起点未知")
    first = day(f"{first[:4]}-{first[4:6]}-{first[6:]}")
    if first[:4] != min(counts) or rows[0][0] < first or rows[-1][0] > now.date().isoformat():
        raise ValueError("指数行情来源日期边界错误")
    for year in {r[0][:4] for r in rows}:
        if year not in counts or sum(r[0][:4] == year for r in rows) > counts[year]:
            raise ValueError("近期行情与来源年份目录不一致")
    if rows[-1][0][:4] != max(counts):
        raise ValueError("指数行情尾年与来源目录不一致")
    deferred_day = rows[-1][0] if pending_today(rows[-1], now.date().isoformat()) else ""
    if rows[-1][0] == now.date().isoformat() and (
        now.time() < time(15, 30) or pending_today(rows[-1], now.date().isoformat())
    ):
        removed = rows.pop()
        counts[removed[0][:4]] -= 1
        counts = {y: n for y, n in counts.items() if n}
    if not rows:
        raise ValueError("来源尚无可用收盘日线")
    result = dict(start=first, end=rows[-1][0], years=counts, total=sum(counts.values()), rows=rows)
    if deferred_day:
        result["deferred_day"] = deferred_day
    return result


def annual(source, code, year, snapshot, now=None):
    _, rows = parse(source, code, year)
    rows = [r for r in rows if r[0] <= snapshot["end"]]
    validate_rows(rows, year)
    if len(rows) != snapshot["years"][str(year)]:
        raise ValueError("指数行情年度来源计数不符，保留断点")
    if str(year) == snapshot["start"][:4] and rows[0][0] != snapshot["start"]:
        raise ValueError("指数行情首年起点不符")
    by_date = {r[0]: r for r in rows}
    expected = [r for r in snapshot["rows"] if r[0][:4] == str(year)]
    # Count and overlap identity are checked before any normalization/deduplication.
    for row in expected:
        actual = by_date.get(row[0])
        if actual == row:
            continue
        # Independent caches can lag beyond midnight or a market holiday. The
        # last snapshot owns only its latest valid date's values, never its keys.
        if (actual is not None and row[0] == snapshot["end"]
                and not pending_today(row, row[0])):
            rows[rows.index(actual)] = row.copy()
            continue
        error = ValueError("年度行情与近期快照集合或内容不一致")
        error.source_metadata = dict(index_code=code, trade_date=row[0], annual=actual, recent=row)
        raise error
    return rows
