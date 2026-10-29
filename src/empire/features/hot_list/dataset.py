"""Atomic complete-date replacement with typed facts and bounded optional metadata."""

import json
from datetime import UTC

from sqlalchemy import bindparam, text

from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.business_schema import require_fixed_source
from empire.core.time import mysql_time
from empire.features.hot_list.contract import (
    CONTRACT,
    DATASET,
    JOB,
    PROJECT,
    REASONS,
    SEATS,
    TABLES,
    day,
    digest,
    number,
    security,
    validate_dates,
    validate_detail,
)
from empire.plugins.infra.collection_state import confirmed_page

EMPTY_AUX = dict(schema=1, counts=[], institution_count=None, related=[])


def json_value(value):
    return json.loads(value) if isinstance(value, str) else value


def read_details(conn, code, stamps, *, heads=None):
    """At most twenty complete dates in three queries, never per-date SQL."""
    if not stamps or len(stamps) > 20:
        raise ValueError("龙虎榜批量详情须为1～20个日期")
    params = dict(code=code, stamps=stamps)
    heads = heads if heads is not None else (
        conn.execute(
            text(
                "SELECT * FROM hot_list_day WHERE unified_code=:code AND list_date IN :stamps"
            ).bindparams(bindparam("stamps", expanding=True)),
            params,
        )
        .mappings()
        .all()
    )
    result = {}
    for head in heads:
        item = dict(head)
        item["list_date"] = item["list_date"].isoformat()
        item["auxiliary"] = json_value(item["auxiliary"])
        item.update(reasons=[], seats=[])
        result[item["list_date"]] = item
    for table, key, columns in ((TABLES[1], "reasons", REASONS), (TABLES[2], "seats", SEATS)):
        rows = (
            conn.execute(
                text(
                    f"SELECT * FROM {table} WHERE unified_code=:code AND list_date IN :stamps ORDER BY list_date,seq LIMIT 200001"
                ).bindparams(bindparam("stamps", expanding=True)),
                params,
            )
            .mappings()
            .all()
        )
        if len(rows) > 200000:
            raise ValueError("龙虎榜批量详情超限")
        for row in rows:
            item = {
                k: number(row[k], pct=k == "change_pct")
                if k
                in (
                    "volume",
                    "turnover",
                    "close_price",
                    "change_pct",
                    "buy_amount",
                    "sell_amount",
                    "net_amount",
                )
                else json_value(row[k])
                if k == "extension"
                else row[k]
                for k in columns
            }
            result[row["list_date"].isoformat()][key].append(item)
    return result


def read_detail(conn, code, stamp):
    return read_details(conn, code, [stamp]).get(stamp)


def upsert(conn, table, values, keys):
    if not values:
        return
    columns = tuple(values[0])
    sql = text(
        f"INSERT INTO {table} ("
        + ",".join("`" + k + "`" for k in columns)
        + ") VALUES ("
        + ",".join(":" + k for k in columns)
        + ") ON DUPLICATE KEY UPDATE "
        + ",".join("`" + k + "`=VALUES(`" + k + "`)" for k in columns if k not in keys)
    )
    for index in range(0, len(values), 200):
        conn.execute(sql, values[index : index + 200])


class HotListDataset:
    DATASETS, PROJECT, JOB = {DATASET}, PROJECT, JOB
    FINGERPRINT_NAMESPACE = "tdx_hot_list_v1"
    FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)

    def normalize(self, envelope):
        p = envelope.raw_payload
        if (
            set(p) != {"page", "mode", "code", "date", "value"}
            or type(p["page"]) is not int
            or not 1 <= p["page"] <= 10000000
        ):
            raise ValueError("龙虎榜消息字段或页码无效")
        mode, code, stamp, value = p["mode"], p["code"], p["date"], p["value"]
        if mode == "manifest":
            if (
                code != ""
                or stamp != ""
                or not isinstance(value, dict)
                or set(value) != {"scope_hash", "securities", "through"}
            ):
                raise ValueError("龙虎榜最终范围证明错误")
            if (
                type(value["securities"]) is not int
                or not 1 <= value["securities"] <= 30000
                or len(value["scope_hash"]) != 64
            ):
                raise ValueError("龙虎榜范围证明无效")
            day(value["through"])
        else:
            security(code)
            if mode == "directory":
                if not isinstance(value, dict) or set(value) != {"dates", "through"} or stamp:
                    raise ValueError("龙虎榜目录消息错误")
                validate_dates(value["dates"], value["through"])
            elif mode == "detail":
                day(stamp)
                validate_detail(value)
            elif mode == "finish":
                if (
                    stamp
                    or not isinstance(value, dict)
                    or set(value) != {"directory_hash", "count", "through"}
                ):
                    raise ValueError("龙虎榜证券完成证明错误")
                day(value["through"])
                if (
                    type(value["count"]) is not int
                    or not 0 <= value["count"] <= 20000
                    or len(value["directory_hash"]) != 64
                ):
                    raise ValueError("龙虎榜证券证明超限")
            else:
                raise ValueError("龙虎榜消息模式未登记")
        return {
            **p,
            "row_count": len(value["seats"]) + len(value["reasons"])
            if mode == "detail"
            else len(value["dates"])
            if mode == "directory"
            else 0,
        }

    def canonical_payload(self, envelope, data):
        return {k: data[k] for k in ("page", "mode", "code", "date", "value")}

    @staticmethod
    def state_unit(data):
        return data["code"] or "manifest"

    def fingerprint_plan(self, envelope, data):
        identity = ":".join((data["mode"], data["code"], data["date"]))
        # Through is evidence of observation, not changing business content.
        content = data["value"]
        if data["mode"] in ("directory", "finish", "manifest"):
            content = {k: v for k, v in content.items() if k != "through"}
        return self.FINGERPRINT_NAMESPACE, {
            identity: (
                content,
                [envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")],
            )
        }

    def fingerprint_subset(self, data, identities):
        return data

    def write(self, conn, envelope, data):
        for table in TABLES:
            require_fixed_source(table, envelope.source)
        code, mode, value = data["code"], data["mode"], data["value"]
        prior = data["archive_state"].get("units", {}).get(code, {})
        observed = envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")
        outcome = dict(
            status="complete", row_count=data["row_count"], written_count=0, confirmed=[]
        )
        if mode != "detail" and observed < prior.get("observed_at", ""):
            return outcome
        if mode == "directory":
            records = (
                conn.execute(
                    text(
                        "SELECT list_date,directory_listed FROM hot_list_day WHERE unified_code=:code ORDER BY list_date DESC LIMIT 20001 FOR UPDATE"
                    ),
                    dict(code=code),
                )
                .mappings()
                .all()
            )
            if len(records) > 20000:
                raise ValueError("龙虎榜历史日头超限")
            existing = {r["list_date"].isoformat(): bool(r["directory_listed"]) for r in records}
            incoming = set(value["dates"])
            rows = [
                dict(
                    unified_code=code,
                    list_date=d,
                    directory_listed=1,
                    detail_status="pending",
                    reason_count=0,
                    seat_count=0,
                    auxiliary=json.dumps(EMPTY_AUX),
                    content_hash=digest(None),
                    version_observed_at=None,
                )
                for d in value["dates"]
                if d not in existing
            ]
            upsert(conn, TABLES[0], rows, ("unified_code", "list_date"))
            for d, listed in existing.items():
                if listed != (d in incoming):
                    conn.execute(
                        text(
                            "UPDATE hot_list_day SET directory_listed=:listed WHERE unified_code=:code AND list_date=:stamp"
                        ),
                        dict(code=code, stamp=d, listed=int(d in incoming)),
                    )
            outcome["written_count"] = len(rows) + sum(
                v != (k in incoming) for k, v in existing.items()
            )
        elif mode == "detail":
            stamp = data["date"]
            # The enclosing shared state row is locked before this method.
            heads = conn.execute(
                text("SELECT * FROM hot_list_day WHERE unified_code=:code AND list_date=:stamp"),
                dict(code=code, stamp=stamp),
            ).mappings().all()
            old = dict(heads[0]) if heads else None
            timestamp = mysql_time(envelope.observed_at)
            if old and old["version_observed_at"] and old["version_observed_at"] > timestamp:
                return outcome
            checksum = digest(value)
            if old and old["content_hash"] == checksum:
                outcome["confirmed"] = [":".join((mode, code, data["date"]))]
                return outcome
            # Directory-created pending heads have no child facts. Complete
            # details and their counts are committed atomically, so these reads
            # cannot contribute previous content on a first detail import.
            if old and old["detail_status"] == "pending" and not (
                old["reason_count"] or old["seat_count"]
            ):
                old.update(reasons=[], seats=[])
            elif old:
                old = read_details(conn, code, [stamp], heads=heads)[stamp]
            keep_reference = value["status"] == "source_empty" and old and old["seats"]
            for table, kind, columns in (
                (TABLES[1], "reasons", REASONS),
                (TABLES[2], "seats", SEATS),
            ):
                if keep_reference:
                    continue
                previous = {r["seq"]: r for r in old[kind]} if old else {}
                incoming = {r["seq"]: r for r in value[kind]}
                changed = []
                for seq, row in incoming.items():
                    if row == previous.get(seq):
                        continue
                    item = dict(unified_code=code, list_date=stamp, **row)
                    if "extension" in item:
                        item["extension"] = json.dumps(item["extension"], ensure_ascii=False)
                    changed.append(item)
                upsert(conn, table, changed, ("unified_code", "list_date", "seq"))
                # Source ordinals are dense within one complete date.
                if previous.keys() - incoming.keys():
                    conn.execute(
                        text(
                            f"DELETE FROM {table} WHERE unified_code=:code AND list_date=:stamp AND seq>:count"
                        ),
                        dict(code=code, stamp=stamp, count=len(incoming)),
                    )
                outcome["written_count"] += len(changed) + len(previous.keys() - incoming.keys())
            header = dict(
                unified_code=code,
                list_date=stamp,
                directory_listed=old["directory_listed"] if old else 1,
                detail_status=value["status"],
                reason_count=len(old["reasons"]) if keep_reference else len(value["reasons"]),
                seat_count=len(old["seats"]) if keep_reference else len(value["seats"]),
                auxiliary=json.dumps(value["auxiliary"], ensure_ascii=False),
                content_hash=checksum,
                version_observed_at=timestamp,
            )
            upsert(conn, TABLES[0], [header], ("unified_code", "list_date"))
            outcome["written_count"] += 1
        elif mode == "finish":
            rows = (
                conn.execute(
                    text(
                        "SELECT list_date,detail_status FROM hot_list_day WHERE unified_code=:code AND directory_listed=1 ORDER BY list_date DESC LIMIT 20001"
                    ),
                    dict(code=code),
                )
                .mappings()
                .all()
            )
            dates = [r["list_date"].isoformat() for r in rows]
            if len(dates) != value["count"] or digest(dates) != value["directory_hash"]:
                raise ValueError("龙虎榜完成证明与SQL日期集合不一致")
            outcome["all_downloaded"] = all(r["detail_status"] != "pending" for r in rows)
        outcome["confirmed"] = [":".join((mode, code, data["date"]))]
        return outcome

    def archive_state(self, envelope, data, outcome, previous):
        code, mode, value = data["code"], data["mode"], data["value"]
        if ":".join((mode, code, data["date"])) not in outcome["confirmed"]:
            return previous
        result = {
            **previous,
            "contract_version": CONTRACT,
            "progress": confirmed_page(envelope, data, previous),
        }
        stamp = envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")
        if mode == "manifest":
            result["manifest"] = {**value, "observed_at": stamp}
        else:
            proof = previous.get("units", {}).get(code, {})
            if mode == "directory":
                proof = {
                    **proof,
                    "count": len(value["dates"]),
                    "directory_hash": digest(value["dates"]),
                    "through": value["through"],
                    "complete": bool(
                        proof.get("complete")
                        and proof.get("directory_hash") == digest(value["dates"])
                        and proof.get("count") == len(value["dates"])
                    ),
                    "observed_at": stamp,
                }
            elif mode == "finish":
                proof = {
                    **proof,
                    **value,
                    "complete": outcome["all_downloaded"],
                    "observed_at": stamp,
                }
            result["units"] = {code: proof}
        return result
