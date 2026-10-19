"""Annual typed facts and source-bound completeness, one fingerprint per annual unit."""

from datetime import UTC
from decimal import Decimal

from sqlalchemy import text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.contracts.security import index_code
from empire.core.time import mysql_time
from empire.features.index_prices.contract import FIELDS, day, validate_rows
from empire.features.index_prices.contract import JOB as JOB
from empire.features.index_prices.contract import PROJECT as PROJECT
from empire.features.indices.contract import digest, label
from empire.plugins.infra.collection_state import confirmed_page

DATASETS = {"index.price.status", "index.price.year"}
FINGERPRINT_NAMESPACE = "ths_index_prices_v1"
FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)
TABLES = {
    "index_daily_price": {"index_code", "trade_date", *FIELDS},
    "index_price_year": {
        "index_code",
        "quote_year",
        "source_count",
        "row_count",
        "first_date",
        "last_date",
        "content_hash",
        "complete",
        "version_observed_at",
    },
}
KEYS = {
    "index_daily_price": ["index_code", "trade_date"],
    "index_price_year": ["index_code", "quote_year"],
}


def normalize(envelope):
    p = envelope.raw_payload
    code = index_code(p.get("code"))
    if type(p.get("page")) is not int or not 1 <= p["page"] <= 100000:
        raise ValueError("指数行情页序无效")
    if envelope.dataset == "index.price.status":
        if (
            set(p) != {"page", "code", "name", "available", "snapshot"}
            or type(p["available"]) is not bool
        ):
            raise ValueError("指数行情状态契约无效")
        label(p["name"])
        s = p["snapshot"]
        if p["available"]:
            if not isinstance(s, dict) or set(s) != {"start", "end", "years", "total"}:
                raise ValueError("指数行情状态缺少来源边界")
            day(s["start"])
            day(s["end"])
            if (
                not isinstance(s["years"], dict)
                or not 1 <= len(s["years"]) <= 40
                or s["start"] > s["end"]
            ):
                raise ValueError("指数行情年份状态无效")
            for y, n in s["years"].items():
                if (
                    not y.isdigit()
                    or not 1990 <= int(y) <= 2100
                    or type(n) is not int
                    or not 1 <= n <= 366
                ):
                    raise ValueError("指数行情年份数量无效")
            if (
                type(s["total"]) is not int
                or s["total"] != sum(s["years"].values())
                or min(s["years"]) != s["start"][:4]
                or max(s["years"]) != s["end"][:4]
            ):
                raise ValueError("指数行情来源状态计数或边界不一致")
        elif s != {}:
            raise ValueError("不可用接口不能伪造行情边界")
        ident = code + ":status"
        rows = []
    else:
        if set(p) != {"page", "code", "year", "mode", "source_count", "start", "end", "rows"}:
            raise ValueError("指数行情年度消息字段无效")
        y, n = p["year"], p["source_count"]
        if (
            type(y) is not int
            or not 1990 <= y <= 2100
            or type(n) is not int
            or not 1 <= n <= 366
            or p["mode"] not in ("full", "recent")
        ):
            raise ValueError("指数行情年度边界无效")
        day(p["start"])
        day(p["end"])
        rows = p["rows"]
        validate_rows(rows, y)
        if len(rows) > n or (p["mode"] == "full" and len(rows) != n):
            raise ValueError("指数行情年度计数不一致")
        if rows[0][0] < p["start"] or rows[-1][0] > p["end"]:
            raise ValueError("指数行情记录越过来源范围")
        if p["mode"] == "full" and p["start"][:4] == str(y) and rows[0][0] != p["start"]:
            raise ValueError("指数行情首年缺少来源起点")
        ident = f"{code}:{y}"
    if envelope.business_key != ident:
        raise ValueError("指数行情业务身份不符")
    return {**p, "identity": ident, "row_count": len(rows)}


def canonical_payload(envelope, data):
    return {k: data[k] for k in envelope.raw_payload}


def content(data):
    return {
        k: v for k, v in data.items() if k not in ("page", "identity", "row_count", "archive_state")
    }


def fingerprint_plan(envelope, data):
    return FINGERPRINT_NAMESPACE, {
        data["identity"]: (
            content(data),
            [envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")],
        )
    }


def fingerprint_subset(data, identities):
    return data


def sql_rows(conn, code, year, lock=False):
    rows = conn.execute(
        text(
            "SELECT trade_date,open,high,low,close,volume,amount FROM index_daily_price "
            "WHERE index_code=:code AND trade_date BETWEEN :first AND :last ORDER BY trade_date"
            + (" FOR UPDATE" if lock else "")
        ),
        dict(code=code, first=f"{year}-01-01", last=f"{year}-12-31"),
    ).all()
    return [[r[0].isoformat()] + [None if v is None else format(Decimal(v).normalize(), "f")
                                for v in r[1:]] for r in rows]


def write(conn, envelope, data):
    require_fixed_source("index_daily_price", envelope.source)
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")
    previous, code, ident = data["archive_state"], data["code"], data["identity"]
    old_version = previous.get("versions", {}).get(ident, "")
    outcome = dict(status="complete", row_count=data["row_count"], written_count=0, confirmed=[])
    if observed < old_version:
        return outcome
    if envelope.dataset == "index.price.status":
        outcome["confirmed"] = [ident]
        return outcome
    year = data["year"]
    head = (
        conn.execute(
            text(
                "SELECT * FROM index_price_year WHERE index_code=:code AND quote_year=:year FOR UPDATE"
            ),
            dict(code=code, year=year),
        )
        .mappings()
        .first()
    )
    if head and mysql_time(envelope.observed_at) < head["version_observed_at"]:
        return outcome
    old = {r[0]: r for r in sql_rows(conn, code, year, True)}
    incoming = {r[0]: r for r in data["rows"]}
    new = incoming if data["mode"] == "full" else {**old, **incoming}
    removed = [dict(code=code, day=d) for d in old.keys() - new.keys()]
    changed = [
        dict(code=code, day=d, **dict(zip(FIELDS, r[1:], strict=True)))
        for d, r in new.items()
        if old.get(d) != r
    ]
    if removed:
        conn.execute(
            text("DELETE FROM index_daily_price WHERE index_code=:code AND trade_date=:day"),
            removed,
        )
    if changed:
        conn.execute(
            text(
                "INSERT INTO index_daily_price(index_code,trade_date,open,high,low,close,volume,amount) "
                "VALUES(:code,:day,:open,:high,:low,:close,:volume,:amount) ON DUPLICATE KEY UPDATE "
                "open=VALUES(open),high=VALUES(high),low=VALUES(low),close=VALUES(close),volume=VALUES(volume),amount=VALUES(amount)"
            ),
            changed,
        )
    canonical = [new[d] for d in sorted(new)]
    complete = bool(
        len(canonical) == data["source_count"]
        and (
            data["mode"] == "full"
            or len(incoming) == data["source_count"]
            or (head and head["complete"])
        )
        and canonical[0][0] >= data["start"]
        and canonical[-1][0] <= data["end"]
    )
    proof = dict(
        source_count=data["source_count"],
        row_count=len(canonical),
        first_date=canonical[0][0],
        last_date=canonical[-1][0],
        content_hash=digest(canonical),
        complete=complete,
    )
    old_proof = (
        {k: (str(head[k]) if k in ("first_date", "last_date") else head[k]) for k in proof}
        if head
        else None
    )
    if old_proof != proof:
        conn.execute(
            text(
                "INSERT INTO index_price_year(index_code,quote_year,source_count,row_count,first_date,last_date,"
                "content_hash,complete,version_observed_at) VALUES(:code,:year,:source_count,:row_count,:first_date,:last_date,"
                ":content_hash,:complete,:observed) ON DUPLICATE KEY UPDATE source_count=VALUES(source_count),"
                "row_count=VALUES(row_count),first_date=VALUES(first_date),last_date=VALUES(last_date),"
                "content_hash=VALUES(content_hash),complete=VALUES(complete),version_observed_at=VALUES(version_observed_at)"
            ),
            dict(code=code, year=year, observed=mysql_time(envelope.observed_at), **proof),
        )
        outcome["written_count"] += 1
    outcome["written_count"] += len(changed) + len(removed)
    outcome["confirmed"] = [ident]
    return outcome


def archive_state(envelope, data, outcome, previous):
    if not outcome["confirmed"]:
        return previous
    versions = dict(previous.get("versions", {}))
    versions[data["identity"]] = envelope.observed_at.astimezone(UTC).isoformat(
        timespec="microseconds"
    )
    statuses = dict(previous.get("indices", {}))
    if envelope.dataset == "index.price.status":
        statuses[data["code"]] = {k: data[k] for k in ("name", "available", "snapshot")}
    if len(statuses) > 1000 or len(versions) > 41000:
        raise ValueError("指数行情状态超过目录/年份容量")
    return dict(
        contract_version=1,
        indices=statuses,
        versions=versions,
        progress=confirmed_page(envelope, data, previous),
    )
