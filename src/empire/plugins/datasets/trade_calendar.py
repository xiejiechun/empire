"""Complete CNINFO calendar months, including explicit non-trading days."""
import calendar
import re
from datetime import UTC, date, timedelta

from sqlalchemy import text

DATASETS = {"calendar.month"}
FIRST_DATE = date(1990, 12, 19)


def month_start(month):
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("月份必须为 YYYY-MM")
    return date.fromisoformat(month + "-01")


def month_dates(month):
    start = month_start(month)
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    start = max(start, FIRST_DATE)
    return [start + timedelta(days=i) for i in range(max(0, (end - start).days + 1))]


def months_between(start, end):
    first, last = month_start(start), month_start(end)
    if first > last:
        return []
    return [f"{index // 12:04d}-{index % 12 + 1:02d}"
            for index in range(first.year * 12 + first.month - 1, last.year * 12 + last.month)]


def validate_rows(month, rows):
    if not isinstance(rows, list) or not 1 <= len(rows) <= 31:
        raise ValueError(f"{month} 来源月份为空或条数无效，不当作全月休市")
    clean = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"trade_date", "is_trade"}
                or type(row["is_trade"]) is not bool or not isinstance(row["trade_date"], str)):
            raise ValueError("交易日历仅允许规范化日期和交易标志")
        day = date.fromisoformat(row["trade_date"])
        if day.isoformat() != row["trade_date"]:
            raise ValueError("日期格式必须为 YYYY-MM-DD")
        clean.append(dict(row))
    clean.sort(key=lambda row: row["trade_date"])
    if [row["trade_date"] for row in clean] != [day.isoformat() for day in month_dates(month)]:
        raise ValueError(f"{month} 日期重复、跨月或月份不完整，不覆盖已有日历")
    return clean


def normalize(envelope):
    payload = envelope.raw_payload
    if set(payload) != {"page", "month", "rows"}:
        raise ValueError("交易日历消息字段无效")
    if type(payload["page"]) is not int or not 1 <= payload["page"] <= 10000:
        raise ValueError("日历月份序号无效")
    rows = validate_rows(payload["month"], payload["rows"])
    return {"page": payload["page"], "month": payload["month"], "rows": rows, "row_count": len(rows)}


def canonical_payload(envelope, normalized):
    return {key: normalized[key] for key in ("page", "month", "rows")}


def write(connection, envelope, data):
    observed = envelope.observed_at.astimezone(UTC).replace(tzinfo=None)
    rows = data["rows"]
    params = {"source": envelope.source, "start": rows[0]["trade_date"], "end": rows[-1]["trade_date"]}
    existing = connection.execute(text("""
        SELECT trade_date,is_trade,updated_at FROM trade_calendar
        WHERE source=:source AND trade_date BETWEEN :start AND :end FOR UPDATE
    """), params).mappings()
    existing = {row["trade_date"].isoformat(): row for row in existing}
    # A late full month must not partly roll back a newer month.
    if any(row["updated_at"] > observed for row in existing.values()):
        return {"status": "complete", "row_count": len(rows), "written_count": 0}
    inserts, updates = [], []
    for row in rows:
        old = existing.get(row["trade_date"])
        value = {**row, "source": envelope.source, "updated_at": observed}
        if old is None:
            inserts.append(value)
        elif bool(old["is_trade"]) != row["is_trade"]:
            updates.append(value)
    if inserts:
        connection.execute(text("""
            INSERT INTO trade_calendar (source,trade_date,is_trade,updated_at)
            VALUES (:source,:trade_date,:is_trade,:updated_at)
        """), inserts)
    if updates:
        connection.execute(text("""
            UPDATE trade_calendar SET is_trade=:is_trade,updated_at=:updated_at
            WHERE source=:source AND trade_date=:trade_date
        """), updates)
    return {"status": "complete", "row_count": len(rows), "written_count": len(inserts) + len(updates)}
