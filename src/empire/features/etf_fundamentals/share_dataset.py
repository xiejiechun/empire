"""One validated complete exchange day, with content-bound collection proof."""

from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.core.time import mysql_time
from empire.features.etf_fundamentals.contract import (
    CONTRACT,
    SHARE_DATASET,
    SHARE_FIELDS,
    day,
    digest,
    number,
    validate_share,
    years,
)
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {SHARE_DATASET}
FINGERPRINT_NAMESPACE = "etf_shares_v1"
FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)
TABLES = ("etf_daily_share", "etf_share_day")


def normalize(envelope):
    p = envelope.raw_payload
    if (
        set(p) != {"page", "date", "rows"}
        or type(p["page"]) is not int
        or not 1 <= p["page"] <= 100000
    ):
        raise ValueError("ETF份额消息契约错误")
    stamp = day(p["date"])
    years(stamp, stamp)
    if envelope.business_key != stamp:
        raise ValueError("ETF份额消息日期身份错误")
    validate_share(p["rows"], envelope.source)
    return {**p, "row_count": len(p["rows"])}


def canonical_payload(envelope, data):
    return {k: data[k] for k in ("page", "date", "rows")}


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {
        data["date"]: (
            data["rows"],
            [envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")],
        )
    }


def fingerprint_subset(data, identities):
    return data


def read_rows(conn, source, stamp, lock=False):
    records = conn.execute(
        text(
            "SELECT unified_code,name,total_shares,source_group,source_type "
            "FROM etf_daily_share WHERE share_date=:day AND source=:source ORDER BY unified_code LIMIT 5001"
            + (" FOR UPDATE" if lock else "")
        ),
        dict(day=stamp, source=source),
    ).all()
    return validate_share([[r[0], r[1], number(r[2]), r[3], r[4]] for r in records], source)


def write(conn, envelope, data):
    stamp, source, rows = data["date"], envelope.source, data["rows"]
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")
    outcome = dict(status="complete", row_count=len(rows), written_count=0, confirmed=[])
    if observed < data["archive_state"].get("observed", {}).get(stamp, ""):
        return outcome
    head = conn.execute(
        text(
            "SELECT key_hash,content_hash,row_count,contract_version "
            "FROM etf_share_day WHERE source=:source AND share_date=:day FOR UPDATE"
        ),
        dict(source=source, day=stamp),
    ).first()
    old = {r[0]: r for r in read_rows(conn, source, stamp, True)}
    if old and not rows:
        raise ValueError("ETF非空日不能自动被空响应清空，须核实来源")
    incoming = {r[0]: r for r in rows}
    removed = [dict(source=source, day=stamp, code=c) for c in old.keys() - incoming.keys()]
    if removed:
        conn.execute(
            text(
                "DELETE FROM etf_daily_share WHERE source=:source AND share_date=:day AND unified_code=:code"
            ),
            removed,
        )
    changed = [
        dict(
            unified_code=c,
            share_date=stamp,
            source=source,
            version_observed_at=mysql_time(envelope.observed_at),
            **dict(zip(SHARE_FIELDS, r[1:], strict=True)),
        )
        for c, r in incoming.items()
        if old.get(c) != r
    ]
    fields = ("unified_code", "share_date", "source", *SHARE_FIELDS, "version_observed_at")
    for offset in range(0, len(changed), 500):
        conn.execute(
            text(
                "INSERT INTO etf_daily_share ("
                + ",".join(fields)
                + ") VALUES ("
                + ",".join(":" + k for k in fields)
                + ") ON DUPLICATE KEY UPDATE "
                + ",".join(k + "=VALUES(" + k + ")" for k in fields[3:])
            ),
            changed[offset : offset + 500],
        )
    expected = (digest([r[0] for r in rows]), digest(rows), len(rows), CONTRACT)
    same = head is not None and tuple(head) == expected
    if not same:
        conn.execute(
            text(
                "INSERT INTO etf_share_day (source,share_date,key_hash,content_hash,row_count,contract_version,version_observed_at) "
                "VALUES(:source,:day,:keys,:content,:count,:version,:observed) ON DUPLICATE KEY UPDATE "
                "key_hash=VALUES(key_hash),content_hash=VALUES(content_hash),row_count=VALUES(row_count),"
                "contract_version=VALUES(contract_version),version_observed_at=VALUES(version_observed_at)"
            ),
            dict(
                source=source,
                day=stamp,
                keys=expected[0],
                content=expected[1],
                count=len(rows),
                version=CONTRACT,
                observed=mysql_time(envelope.observed_at),
            ),
        )
    return {
        **outcome,
        "confirmed": [stamp],
        "written_count": len(removed) + len(changed) + int(not same),
    }


def archive_state(envelope, data, outcome, previous):
    if not outcome["confirmed"]:
        return previous
    return dict(
        contract_version=CONTRACT,
        observed={
            **previous.get("observed", {}),
            data["date"]: envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds"),
        },
        progress=confirmed_page(envelope, data, previous),
    )
