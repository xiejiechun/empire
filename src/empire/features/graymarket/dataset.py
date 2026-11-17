"""One complete source-date snapshot; shared archive owns confirmation and deletion."""

from datetime import UTC, time

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import CHINA
from empire.features.graymarket.codec import pack, unpack
from empire.features.graymarket.contract import (
    CONTRACT,
    DATASET,
    FIELDS,
    JOB,
    PROJECT,
    TABLES,
    day,
    digest,
    number,
    validate,
)
from empire.plugins.infra.collection_state import confirmed_page


def read_rows(conn, stamp):
    records = conn.execute(
        text(
            "SELECT unified_code,"
            + ",".join(FIELDS)
            + " FROM graymarket_daily WHERE trade_date=:day ORDER BY unified_code LIMIT 10001"
        ),
        dict(day=stamp),
    ).all()
    rows = []
    for r in records:
        rows.append(
            [
                r[0],
                r[1],
                *[number(v) for v in r[2:5]],
                number(r[5], scale=10, integer_digits=10),
                number(r[6], scale=3, integer_digits=15),
                number(r[7], scale=10, integer_digits=10),
                r[8],
                r[9],
            ]
        )
    return validate(rows) if rows else []


class GraymarketDataset:
    DATASETS = {DATASET}
    PROJECT, JOB = PROJECT, JOB
    FINGERPRINT_NAMESPACE = "eastmoney_graymarket_v1"
    FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)

    def normalize(self, envelope):
        p = envelope.raw_payload
        if (
            set(p) != {"page", "date", "rows", "source_latest"}
            or type(p["page"]) is not int
            or p["page"] < 1
        ):
            raise ValueError("明盘暗盘资金榜消息字段无效")
        if (
            not day(p["date"])
            <= day(p["source_latest"])
            <= envelope.observed_at.astimezone(CHINA).date().isoformat()
        ):
            raise ValueError("明盘暗盘资金榜未来日期消息")
        rows = unpack(p["rows"])
        local = envelope.observed_at.astimezone(CHINA)
        if p["date"] == local.date().isoformat() and local.time().replace(tzinfo=None) < time(15, 30):
            raise ValueError("盘中资金榜不得进入MySQL")
        if envelope.business_key != p["date"]:
            raise ValueError("资金榜消息身份错误")
        return {**p, "rows": rows, "row_count": len(rows)}

    def canonical_payload(self, envelope, data):
        return {
            **{k: data[k] for k in ("page", "date", "source_latest")},
            "rows": pack(data["rows"]),
        }

    def fingerprint_plan(self, envelope, data):
        return self.FINGERPRINT_NAMESPACE, {
            data["date"]: (
                data["rows"],
                [envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")],
            )
        }

    def fingerprint_subset(self, data, identities):
        return data

    def write(self, conn, envelope, data):
        for table in TABLES:
            require_fixed_source(table, envelope.source)
        stamp, rows = data["date"], data["rows"]
        observed = envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")
        outcome = dict(status="complete", row_count=len(rows), written_count=0, confirmed=[])
        if observed < data["archive_state"].get("observed", {}).get(stamp, ""):
            return outcome
        old = {r[0]: r for r in read_rows(conn, stamp)}
        incoming = {r[0]: r for r in rows}
        if old and not incoming:
            raise ValueError("有效空响应不能自动覆盖已有非空证券集合，须核实来源")
        removed = old.keys() - incoming.keys()
        if removed:
            conn.execute(
                text("DELETE FROM graymarket_daily WHERE trade_date=:day AND unified_code=:name"),
                [dict(day=stamp, name=n) for n in removed],
            )
        changed = [
            dict(zip(("unified_code", *FIELDS), r, strict=True), trade_date=stamp)
            for n, r in incoming.items()
            if old.get(n) != r
        ]
        columns = ("trade_date", "unified_code", *FIELDS)
        for offset in range(0, len(changed), 500):
            conn.execute(
                text(
                    "INSERT INTO graymarket_daily ("
                    + ",".join(columns)
                    + ") VALUES ("
                    + ",".join(":" + c for c in columns)
                    + ") ON DUPLICATE KEY UPDATE "
                    + ",".join(c + "=VALUES(" + c + ")" for c in FIELDS)
                ),
                changed[offset : offset + 500],
            )
        head = conn.execute(
            text(
                "SELECT content_hash,row_count,contract_version "
                "FROM graymarket_day WHERE trade_date=:day FOR UPDATE"
            ),
            dict(day=stamp),
        ).first()
        expected = (digest(rows), len(rows), CONTRACT)
        if head is None or tuple(head) != expected:
            conn.execute(
                text(
                    "INSERT INTO graymarket_day "
                    "(trade_date,content_hash,row_count,contract_version) "
                    "VALUES(:day,:hash,:count,:contract) ON DUPLICATE KEY UPDATE "
                    "content_hash=VALUES(content_hash),row_count=VALUES(row_count),"
                    "contract_version=VALUES(contract_version)"
                ),
                dict(day=stamp, hash=expected[0], count=len(rows), contract=CONTRACT),
            )
        outcome.update(
            written_count=len(changed)
            + len(removed)
            + int(head is None or tuple(head) != expected),
            confirmed=[stamp],
        )
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if not outcome["confirmed"]:
            return previous
        observed = dict(previous.get("observed", {}))
        observed[data["date"]] = envelope.observed_at.astimezone(UTC).isoformat(
            timespec="microseconds"
        )
        return dict(
            observed=observed,
            progress=confirmed_page(envelope, data, previous),
            source_latest=max(previous.get("source_latest", ""), data["source_latest"]),
        )
