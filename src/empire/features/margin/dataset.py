"""One security snapshot per transaction; unchanged facts never receive DML."""

from datetime import UTC

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import CHINA
from empire.features.margin.contract import (
    CONTRACT,
    DATASET,
    FIELDS,
    JOB,
    PROJECT,
    digest,
    number,
    pack,
    security,
    unpack,
    validate,
)
from empire.plugins.infra.collection_state import confirmed_page


def read_rows(conn, code, *, lock=False):
    records = conn.execute(
        text(
            "SELECT trade_date,"
            + ",".join(FIELDS)
            + " FROM margin_daily WHERE unified_code=:code ORDER BY trade_date DESC LIMIT 10001"
            + (" FOR UPDATE" if lock else "")
        ),
        dict(code=code),
    ).all()
    return [
        [r[0].isoformat(), *[number(v, optional=i < 3) for i, v in enumerate(r[1:])]]
        for r in records
    ]


class MarginDataset:
    DATASETS = {DATASET}
    PROJECT, JOB = PROJECT, JOB
    FINGERPRINT_NAMESPACE = "tdx_margin_v1"
    FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)

    def normalize(self, envelope):
        p = envelope.raw_payload
        if (
            set(p) != {"page", "code", "through", "rows"}
            or type(p["page"]) is not int
            or p["page"] < 1
        ):
            raise ValueError("融资融券消息字段无效")
        security(p["code"])
        if p["through"] > envelope.observed_at.astimezone(CHINA).date().isoformat():
            raise ValueError("融资融券消息观测日期超前")
        rows = validate(unpack(p["rows"]), p["through"])
        return {**p, "rows": rows, "row_count": len(rows)}

    def canonical_payload(self, envelope, data):
        return {**{k: data[k] for k in ("page", "code", "through")}, "rows": pack(data["rows"])}

    def fingerprint_plan(self, envelope, data):
        return self.FINGERPRINT_NAMESPACE, {
            data["code"]: (
                data["rows"],
                [envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")],
            )
        }

    def fingerprint_subset(self, data, identities):
        return data

    def write(self, conn, envelope, data):
        require_fixed_source("margin_daily", envelope.source)
        code, rows = data["code"], data["rows"]
        stamp = envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")
        previous = data["archive_state"].get("observed", {}).get(code, "")
        outcome = dict(status="complete", row_count=len(rows), written_count=0, confirmed=[])
        if stamp < previous:
            return outcome
        old = {r[0]: r for r in read_rows(conn, code, lock=True)}
        new = {r[0]: r for r in rows}
        # Complete source snapshot owns only this security, never another key.
        removed = old.keys() - new.keys()
        if removed:
            conn.execute(
                text("DELETE FROM margin_daily WHERE unified_code=:code AND trade_date=:day"),
                [dict(code=code, day=d) for d in removed],
            )
        changed = [
            dict(zip(("trade_date", *FIELDS), r, strict=True), unified_code=code)
            for d, r in new.items()
            if old.get(d) != r
        ]
        columns = ("unified_code", "trade_date", *FIELDS)
        for i in range(0, len(changed), 500):
            conn.execute(
                text(
                    "INSERT INTO margin_daily("
                    + ",".join(columns)
                    + ") VALUES("
                    + ",".join(":" + k for k in columns)
                    + ") ON DUPLICATE KEY UPDATE "
                    + ",".join(k + "=VALUES(" + k + ")" for k in FIELDS)
                ),
                changed[i : i + 500],
            )
        head = conn.execute(
            text(
                "SELECT content_hash,row_count,first_date,last_date,contract_version "
                "FROM margin_security WHERE unified_code=:code FOR UPDATE"
            ),
            dict(code=code),
        ).first()
        expected = (
            digest(rows),
            len(rows),
            rows[-1][0] if rows else None,
            rows[0][0] if rows else None,
            CONTRACT,
        )
        actual = (
            None
            if head is None
            else (
                head[0],
                head[1],
                head[2].isoformat() if head[2] else None,
                head[3].isoformat() if head[3] else None,
                head[4],
            )
        )
        if actual != expected:
            conn.execute(
                text(
                    "INSERT INTO margin_security "
                    "(unified_code,content_hash,row_count,first_date,last_date,contract_version) "
                    "VALUES(:code,:hash,:count,:first,:last,:contract) ON DUPLICATE KEY UPDATE "
                    "content_hash=VALUES(content_hash),row_count=VALUES(row_count),first_date=VALUES(first_date),"
                    "last_date=VALUES(last_date),contract_version=VALUES(contract_version)"
                ),
                dict(
                    code=code,
                    hash=expected[0],
                    count=expected[1],
                    first=expected[2],
                    last=expected[3],
                    contract=CONTRACT,
                ),
            )
        outcome.update(
            written_count=len(changed) + len(removed) + int(actual != expected), confirmed=[code]
        )
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        if not outcome["confirmed"]:
            return previous
        observed = dict(previous.get("observed", {}))
        observed[data["code"]] = envelope.observed_at.astimezone(UTC).isoformat(
            timespec="microseconds"
        )
        return dict(observed=observed, progress=confirmed_page(envelope, data, previous))
