"""Business-owned calendar.dataset."""
from datetime import UTC

from sqlalchemy import text

from empire.contracts.business_schema import require_fixed_source
from empire.core.time import mysql_time
from empire.features.calendar.contract import FINGERPRINT_NAMESPACE, validate_rows
from empire.features.calendar.contract import FINGERPRINT_VERSION as FINGERPRINT_VERSION
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {"calendar.month"}


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
    require_fixed_source("trade_calendar", envelope.source)
    observed = mysql_time(envelope.observed_at)
    rows = data["rows"]
    previous = data["archive_state"].get("observed", {}).get(data["month"])
    if previous and envelope.observed_at.isoformat(timespec="microseconds") <= previous:
        return {"status": "complete", "row_count": len(rows), "written_count": 0, "confirmed": []}
    params = {"source": envelope.source, "start": rows[0]["trade_date"], "end": rows[-1]["trade_date"]}
    existing = connection.execute(text("""
        SELECT trade_date,is_trade,updated_at FROM trade_calendar
        WHERE trade_date BETWEEN :start AND :end FOR UPDATE
    """), params).mappings()
    existing = {row["trade_date"].isoformat(): row for row in existing}
    # A late full month must not partly roll back a newer month.
    if any(row["updated_at"] > observed for row in existing.values()):
        return {"status": "complete", "row_count": len(rows), "written_count": 0, "confirmed": []}
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
            INSERT INTO trade_calendar (trade_date,is_trade,updated_at)
            VALUES (:trade_date,:is_trade,:updated_at)
        """), inserts)
    if updates:
        connection.execute(text("""
            UPDATE trade_calendar SET is_trade=:is_trade,updated_at=:updated_at
            WHERE trade_date=:trade_date
        """), updates)
    return {"status": "complete", "row_count": len(rows), "written_count": len(inserts) + len(updates),
            "confirmed": [data["month"]]}


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {data["month"]: (data["rows"], [
        envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")])}


def fingerprint_subset(data, identities):
    return data


def archive_state(envelope, data, outcome, previous):
    observed = {**previous.get("observed", {}),
                data["month"]: envelope.observed_at.isoformat(timespec="microseconds")}
    return {"progress": confirmed_page(envelope, data, previous), "observed": observed}
