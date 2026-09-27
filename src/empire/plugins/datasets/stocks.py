"""Stock identity validation and atomic replacement of one current business list."""

import hashlib
import json
import re
from datetime import datetime

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.stocks import normalize_sina_stock
from empire.core.time import mysql_time

DATASETS = {"stock.universe.start", "stock.universe.page", "stock.universe.complete"}
FINGERPRINT_NAMESPACE = "stocks"
FINGERPRINT_VERSION = ArchiveVersion(("china", "snapshot"), observed_index=0)


def aggregate_result_keys(prefix, source):
    return {
        "committed": f"{prefix}:stocks:committed:{source}",
        "result": f"{prefix}:stocks:result:{source}",
    }


def normalize(envelope) -> dict:
    payload = envelope.raw_payload
    required = {"snapshot_id", "started_at", "expected_count", "page_size", "node"}
    if envelope.dataset == "stock.universe.page":
        required |= {"page", "rows"}
    if not required <= payload.keys():
        raise ValueError(f"Stock payload is missing required fields: {sorted(required - payload.keys())}")
    snapshot = payload.get("snapshot_id")
    if not isinstance(snapshot, str) or not re.fullmatch(r"[0-9a-f]{32}", snapshot):
        raise ValueError("Invalid stock snapshot ID")
    if envelope.batch_id != snapshot:
        raise ValueError("Snapshot and envelope batch IDs differ")
    started = datetime.fromisoformat(payload["started_at"])
    if started.tzinfo is None:
        raise ValueError("Stock snapshot timestamp must include timezone")
    count, size = payload["expected_count"], payload["page_size"]
    if type(count) is not int or not 1 <= count <= 100000:
        raise ValueError("Stock count must be positive and bounded")
    if type(size) is not int or not 1 <= size <= 80:
        raise ValueError("Invalid Sina page size")
    if payload.get("node") != "hs_a":
        raise ValueError("Only the explicitly configured hs_a universe is supported")
    result = {"snapshot_id": snapshot, "source": envelope.source, "node": "hs_a",
              "started_at": mysql_time(started),
              "expected_count": count, "page_size": size}
    if envelope.dataset == "stock.universe.page":
        page = payload["page"]
        if type(page) is not int or not 1 <= page <= (count + size - 1) // size:
            raise ValueError("Stock page outside expected range")
        rows = payload["rows"]
        if not isinstance(rows, list) or len(rows) != min(size, count - (page - 1) * size):
            raise ValueError("Stock page count does not match declared coverage")
        normalized = [normalize_row(row) for row in rows]
        symbols = [row["source_symbol"] for row in normalized]
        if any(a <= b for a, b in zip(symbols, symbols[1:])):
            raise ValueError("Stock symbols are duplicated or not sorted descending")
        digest = hashlib.sha256(json.dumps(normalized, sort_keys=True, ensure_ascii=False,
                                           separators=(",", ":")).encode()).hexdigest()
        result.update(page=page, rows=normalized, row_count=len(rows), identity_hash=digest,
                      first_symbol=symbols[0], last_symbol=symbols[-1])
    elif envelope.dataset == "stock.universe.complete":
        pages = (count + size - 1) // size
        if (payload.get("collected") != count or payload.get("count_after") != count
                or payload.get("pages") != pages or payload.get("terminal_rows") != []):
            raise ValueError("Stock completion evidence does not match expected coverage")
        result.update(pages=pages, finished_at=mysql_time(envelope.observed_at))
    return result



def normalize_row(row: dict) -> dict:
    if not isinstance(row, dict):
        raise ValueError("股票记录必须是对象")
    normalized = normalize_sina_stock({**row, "symbol": row.get("source_symbol", row.get("symbol"))})
    for key in ("unified_code", "market", "source_symbol"):
        if key in row and row[key] != normalized[key]:
            raise ValueError(f"股票规范字段 {key} 与来源代码不一致")
    return normalized


def canonical_payload(envelope, normalized: dict) -> dict:
    """Keep contract fields and normalized business values, never quote response extras."""
    allowed = {"snapshot_id", "started_at", "expected_count", "page_size", "node"}
    if envelope.dataset.endswith(".page"):
        allowed |= {"page"}
    elif envelope.dataset.endswith(".complete"):
        allowed |= {"pages", "collected", "count_after", "terminal_rows"}
    elif envelope.dataset.endswith(".start"):
        allowed |= {"count_before"}
    payload = {key: value for key, value in envelope.raw_payload.items() if key in allowed}
    if "rows" in normalized:
        payload["rows"] = normalized["rows"]
    return payload


def assemble(records: list[dict], *, include_rows: bool = True) -> dict | None:
    """Validate all pages before handing one replacement to the SQL transaction."""
    complete = [r for r in records if r["envelope"].dataset.endswith(".complete")]
    if not complete:
        return None
    data = complete[0]["normalized"]
    fields = ("source", "node", "snapshot_id", "started_at", "expected_count", "page_size")
    if any(any(record["normalized"][field] != data[field] for field in fields) for record in records):
        raise ValueError("同一股票采集批次的元数据不一致")
    pages = {}
    for record in records:
        page = record["normalized"]
        if "page" not in page:
            continue
        if page["page"] in pages and pages[page["page"]]["identity_hash"] != page["identity_hash"]:
            raise ValueError("同一分页的股票身份或名称发生变化，需要重新采集")
        pages[page["page"]] = page
    if sorted(pages) != list(range(1, data["pages"] + 1)):
        raise ValueError("股票分页缺失，未替换当前列表")
    ordered = [pages[number] for number in sorted(pages)]
    if (sum(page["row_count"] for page in ordered) != data["expected_count"]
            or not all(a["last_symbol"] > b["first_symbol"] for a, b in zip(ordered, ordered[1:]))):
        raise ValueError("股票重复、数量不足或分页边界变化，未替换当前列表")
    if not include_rows:
        return dict(data)
    rows = [row for page in ordered for row in page["rows"]]
    if len(rows) != data["expected_count"] or len({row["unified_code"] for row in rows}) != len(rows):
        raise ValueError("股票身份重复或实际行数变化，未替换当前列表")
    return {**data, "rows": rows}


def write(connection, envelope, data: dict) -> dict:
    latest = data["archive_state"].get("version")
    incoming = [data["started_at"].isoformat(timespec="microseconds"), data["snapshot_id"]]
    if latest and incoming <= latest:
        return {"status": "replayed" if data["snapshot_id"] == latest[1] else "superseded",
                "row_count": 0, "confirmed": []}
    previous = connection.execute(text("""
        SELECT node,unified_code,code,name,market,source_symbol FROM stock
        WHERE source=:source FOR UPDATE
    """), data).mappings().all()
    incoming = {row["unified_code"]: {**row, "node": data["node"]} for row in data["rows"]}
    if {row["unified_code"]: dict(row) for row in previous} == incoming:
        return {"status": "complete", "row_count": len(data["rows"]), "written_count": 0,
                "confirmed": ["current"]}
    # Both removal and insertion are inside MySQLPlugin's single InnoDB transaction.
    connection.execute(text("DELETE FROM stock WHERE source=:source"), data)
    insert_rows(connection, data)
    return {"status": "complete", "row_count": len(data["rows"]),
            "written_count": len(data["rows"]), "confirmed": ["current"]}


def insert_rows(connection, data: dict) -> None:
    for offset in range(0, len(data["rows"]), 1000):
        connection.execute(text("""
            INSERT INTO stock (source, node, unified_code, code, name, market, source_symbol)
            VALUES (:source, :node, :unified_code, :code, :name, :market, :source_symbol)
        """), [{**row, "source": data["source"], "node": data["node"]}
                for row in data["rows"][offset:offset + 1000]])


def fingerprint_plan(envelope, data):
    content = {"node": data["node"], "rows": sorted(data["rows"], key=lambda row: row["unified_code"])}
    return FINGERPRINT_NAMESPACE, {"current": (content, [data["started_at"].isoformat(timespec="microseconds"),
                                             data["snapshot_id"]])}


def fingerprint_subset(data, identities):
    return data


def archive_state(envelope, data, outcome, previous):
    snapshot = {"snapshot_id": data["snapshot_id"], "started_at": data["started_at"].isoformat(),
                "finished_at": data["finished_at"].isoformat(), "row_count": data["expected_count"]}
    return {"version": [data["started_at"].isoformat(timespec="microseconds"), data["snapshot_id"]],
            "progress": {**snapshot, "status": "complete", "expected_count": data["expected_count"],
                         "error_text": ""},
            "publication": snapshot if outcome["written_count"] or not previous.get("publication")
            else previous["publication"]}
