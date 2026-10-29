"""One complete source-date snapshot; shared archive owns confirmation and deletion."""

from datetime import UTC

from sqlalchemy import bindparam, text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import CHINA
from empire.features.industry_margin.contract import (
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


def read_days(conn, stamps):
    if not stamps or len(stamps) > 31:
        raise ValueError("行业融资融券批量审计限1至31天")
    records = conn.execute(
        text(
            "SELECT trade_date,industry_name,"
            + ",".join(FIELDS)
            + " FROM industry_margin_daily WHERE trade_date IN :days "
            "ORDER BY trade_date,industry_name LIMIT 7937"
        ).bindparams(bindparam("days", expanding=True)),
        dict(days=stamps),
    ).all()
    if len(records) > 7936:
        raise ValueError("行业融资融券批量完整集合超限")
    result = {stamp: [] for stamp in stamps}
    for row in records:
        result[row[0].isoformat()].append([row[1], *[number(v) for v in row[2:]]])
    return {stamp: sorted(rows, key=lambda r: r[0]) for stamp, rows in result.items()}


def read_rows(conn, stamp):
    return read_days(conn, [stamp])[stamp]


class IndustryMarginDataset:
    DATASETS = {DATASET}
    PROJECT, JOB = PROJECT, JOB
    FINGERPRINT_NAMESPACE = "tdx_industry_margin_v1"
    FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)

    def normalize(self, envelope):
        p = envelope.raw_payload
        if (
            set(p) != {"page", "date", "rows", "source_latest"}
            or type(p["page"]) is not int
            or p["page"] < 1
        ):
            raise ValueError("行业融资融券消息字段无效")
        if (
            not day(p["date"])
            <= day(p["source_latest"])
            <= envelope.observed_at.astimezone(CHINA).date().isoformat()
        ):
            raise ValueError("行业融资融券未来日期消息")
        rows = validate(p["rows"])
        return {**p, "row_count": len(rows)}

    def canonical_payload(self, envelope, data):
        return {k: data[k] for k in ("page", "date", "rows", "source_latest")}

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
            raise ValueError("有效空响应不能自动覆盖已有非空行业集合，须核实来源")
        removed = old.keys() - incoming.keys()
        if removed:
            conn.execute(
                text(
                    "DELETE FROM industry_margin_daily "
                    "WHERE trade_date=:day AND industry_name=:name"
                ),
                [dict(day=stamp, name=n) for n in removed],
            )
        changed = [
            dict(zip(("industry_name", *FIELDS), r, strict=True), trade_date=stamp)
            for n, r in incoming.items()
            if old.get(n) != r
        ]
        columns = ("trade_date", "industry_name", *FIELDS)
        if changed:
            conn.execute(
                text(
                    "INSERT INTO industry_margin_daily ("
                    + ",".join(columns)
                    + ") VALUES ("
                    + ",".join(":" + c for c in columns)
                    + ") ON DUPLICATE KEY UPDATE "
                    + ",".join(c + "=VALUES(" + c + ")" for c in FIELDS)
                ),
                changed,
            )
        head = conn.execute(
            text(
                "SELECT content_hash,row_count,contract_version "
                "FROM industry_margin_day WHERE trade_date=:day FOR UPDATE"
            ),
            dict(day=stamp),
        ).first()
        expected = (digest(rows), len(rows), CONTRACT)
        if head is None or tuple(head) != expected:
            conn.execute(
                text(
                    "INSERT INTO industry_margin_day "
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
