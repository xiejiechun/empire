"""Annual NAV range merge; empty observations also carry version authority."""

from datetime import UTC, date, timedelta

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import mysql_time
from empire.features.etf_fundamentals.contract import (
    CONTRACT,
    NAV_DATASET,
    NAV_FIELDS,
    NUMERIC,
    coverage_through,
    digest,
    number,
    security,
    validate_nav,
    years,
)
from empire.plugins.infra.collection_state import confirmed_page
from empire.sources.yuanhang_ranges import replace_range

DATASETS = {NAV_DATASET}
FINGERPRINT_NAMESPACE = "etf_nav_v1"
FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)
TABLES = ("etf_daily_nav", "etf_nav_year")


def normalize(envelope):
    p = envelope.raw_payload
    if (
        set(p) != {"page", "code", "start", "through", "rows"}
        or type(p["page"]) is not int
        or not 1 <= p["page"] <= 750000
    ):
        raise ValueError("ETF净值消息契约错误")
    security(p["code"])
    validate_nav(p["rows"], p["start"], p["through"])
    years(p["start"], p["through"])
    identity = p["code"] + ":" + p["start"][:4]
    if envelope.source != "ttjj" or envelope.business_key != identity:
        raise ValueError("ETF净值来源或消息身份错误")
    return {**p, "year": int(p["start"][:4]), "identity": identity, "row_count": len(p["rows"])}


def canonical_payload(envelope, data):
    return {k: data[k] for k in ("page", "code", "start", "through", "rows")}


def date_keys(data):
    stamp, end = date.fromisoformat(data["start"]), date.fromisoformat(data["through"])
    incoming = {r[0]: r for r in data["rows"]}
    result = {}
    while stamp <= end:
        s = stamp.isoformat()
        result[data["code"] + ":" + s] = incoming.get(s)
        stamp += timedelta(days=1)
    return result


def fingerprint_plan(envelope, data):
    observed = [envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")]
    return FINGERPRINT_NAMESPACE, {key: (row, observed) for key, row in date_keys(data).items()}


def fingerprint_subset(data, identities):
    return {**data, "pending_days": identities}


def state_unit(data):
    return data["code"]


def read_rows(conn, code, year, lock=False):
    records = conn.execute(
        text(
            "SELECT nav_date," + ",".join(NAV_FIELDS) + " FROM etf_daily_nav "
            "WHERE unified_code=:code AND nav_date BETWEEN :first AND :last ORDER BY nav_date LIMIT 367"
            + (" FOR UPDATE" if lock else "")
        ),
        dict(code=code, first=f"{year}-01-01", last=f"{year}-12-31"),
    ).all()
    rows = [
        [
            r[0].isoformat(),
            *[
                number(v) if field in NUMERIC else v.isoformat() if isinstance(v, date) else v
                for field, v in zip(NAV_FIELDS, r[1:], strict=True)
            ],
        ]
        for r in records
    ]
    return validate_nav(rows, f"{year}-01-01", f"{year}-12-31")


def read_groups(conn, codes, year):
    """Bounded batched annual audit, including securities with an empty source year."""
    if not 1 <= len(codes) <= 64 or len(set(codes)) != len(codes):
        raise ValueError("ETF年度核查证券批次无效")
    args = {f"c{i}": security(c) for i, c in enumerate(codes)}
    names = ",".join(":" + k for k in args)
    args.update(first=f"{year}-01-01", last=f"{year}-12-31")
    records = conn.execute(
        text(
            "SELECT unified_code,nav_date,"
            + ",".join(NAV_FIELDS)
            + " FROM etf_daily_nav WHERE unified_code IN ("
            + names
            + ") AND nav_date BETWEEN :first AND :last "
            "ORDER BY unified_code,nav_date LIMIT 23425"
        ),
        args,
    ).all()
    if len(records) > 64 * 366:
        raise ValueError("ETF年度核查行数超界")
    groups = {code: [] for code in codes}
    for record in records:
        groups[record[0]].append(
            [
                record[1].isoformat(),
                *[
                    number(v) if f in NUMERIC else v.isoformat() if isinstance(v, date) else v
                    for f, v in zip(NAV_FIELDS, record[2:], strict=True)
                ],
            ]
        )
    return {
        code: validate_nav(rows, f"{year}-01-01", f"{year}-12-31") for code, rows in groups.items()
    }


def write(conn, envelope, data):
    require_fixed_source("etf_daily_nav", envelope.source)
    code, year = data["code"], data["year"]
    unit = data["archive_state"].get("units", {}).get(code, {})
    ranges = unit.get("ranges", {})
    segments = ranges.get(str(year), [])
    old = read_rows(conn, code, year, True)
    if old and not segments:
        raise ValueError("ETF净值事实缺少版本覆盖，须显式维护")
    pending = data.get("pending_days", set(date_keys(data)))
    incoming, groups = {r[0]: r for r in data["rows"]}, []
    for key in date_keys(data):
        if key in pending:
            stamp = key[-10:]
            if groups and date.fromisoformat(stamp) == date.fromisoformat(
                groups[-1][-1]
            ) + timedelta(days=1):
                groups[-1].append(stamp)
            else:
                groups.append([stamp])
    rows, accepted = old, []
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")
    for group in groups:
        rows, segments, granted = replace_range(
            rows,
            [incoming[d] for d in group if d in incoming],
            year=year,
            start=group[0],
            end=group[-1],
            observed=observed,
            segments=segments,
        )
        accepted.extend(code + ":" + d for d in granted)
    outcome = dict(
        status="complete", row_count=data["row_count"], written_count=0, confirmed=accepted
    )
    if not accepted:
        return outcome
    before, after = {r[0]: r for r in old}, {r[0]: r for r in rows}
    removed = [dict(code=code, day=d) for d in before.keys() - after.keys()]
    if removed:
        conn.execute(
            text("DELETE FROM etf_daily_nav WHERE unified_code=:code AND nav_date=:day"), removed
        )
    changed = [
        dict(
            unified_code=code,
            nav_date=d,
            version_observed_at=mysql_time(envelope.observed_at),
            **dict(zip(NAV_FIELDS, r[1:], strict=True)),
        )
        for d, r in after.items()
        if before.get(d) != r
    ]
    fields = ("unified_code", "nav_date", *NAV_FIELDS, "version_observed_at")
    if changed:
        conn.execute(
            text(
                "INSERT INTO etf_daily_nav ("
                + ",".join(fields)
                + ") VALUES ("
                + ",".join(":" + k for k in fields)
                + ") ON DUPLICATE KEY UPDATE "
                + ",".join(k + "=VALUES(" + k + ")" for k in fields[2:])
            ),
            changed,
        )
    head = (
        conn.execute(
            text(
                "SELECT * FROM etf_nav_year WHERE unified_code=:code AND nav_year=:year FOR UPDATE"
            ),
            dict(code=code, year=year),
        )
        .mappings()
        .first()
    )
    # Keep the range-bound observation in collection_state; proof contains business coverage only.
    proof = dict(
        row_count=len(rows),
        first_date=rows[0][0] if rows else None,
        last_date=rows[-1][0] if rows else None,
        key_hash=digest([r[0] for r in rows]),
        content_hash=digest(rows),
        verified_through=coverage_through(segments, year),
        contract_version=CONTRACT,
    )
    same = head and all(
        (v.isoformat() if isinstance(v := head[k], date) else v) == value
        for k, value in proof.items()
    )
    if not same:
        columns = ("unified_code", "nav_year", *proof, "version_observed_at")
        conn.execute(
            text(
                "INSERT INTO etf_nav_year ("
                + ",".join(columns)
                + ") VALUES ("
                + ",".join(":" + k for k in columns)
                + ") ON DUPLICATE KEY UPDATE "
                + ",".join(k + "=VALUES(" + k + ")" for k in columns[2:])
            ),
            dict(
                unified_code=code,
                nav_year=year,
                **proof,
                version_observed_at=mysql_time(envelope.observed_at),
            ),
        )
    return {
        **outcome,
        "written_count": len(changed) + len(removed) + int(not same),
        "unit": dict(ranges={**ranges, str(year): segments}),
    }


def archive_state(envelope, data, outcome, previous):
    if not outcome["confirmed"]:
        return previous
    return dict(
        contract_version=CONTRACT,
        units={**previous.get("units", {}), data["code"]: outcome["unit"]},
        progress=confirmed_page(envelope, data, previous),
    )
