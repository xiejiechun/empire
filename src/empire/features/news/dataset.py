"""Canonical news envelopes and the sole idempotent SQL archive mapping."""
import json
from datetime import UTC, datetime

from sqlalchemy import bindparam, text

from empire.core.time import mysql_time
from empire.features.news.contract import DATASETS as DATASETS
from empire.features.news.contract import FINGERPRINT_NAMESPACE, news_id
from empire.features.news.contract import FINGERPRINT_VERSION as FINGERPRINT_VERSION
from empire.plugins.infra.collection_state import confirmed_page


def normalize(envelope):
    payload = envelope.raw_payload
    page, rows = payload.get("page"), payload.get("rows")
    if type(page) is not int or not 1 <= page <= 100000:
        raise ValueError("新闻分页编号无效")
    if not isinstance(rows, list) or len(rows) > 50:
        raise ValueError("新闻分页最多 50 条")
    clean = []
    fields = {"news_id", "title", "content", "published_at", "source_updated_at", "is_important", "tags", "url"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != fields:
            raise ValueError("新闻只允许规范化业务字段")
        news_id(row["news_id"])
        if (not isinstance(row["title"], str) or not 1 <= len(row["title"]) <= 256
                or not isinstance(row["content"], str) or not 1 <= len(row["content"].encode()) <= 200000
                or type(row["is_important"]) is not bool):
            raise ValueError("新闻正文、标题或重要性无效")
        for field in ("published_at", "source_updated_at"):
            date = datetime.fromisoformat(row[field])
            if date.tzinfo is None:
                raise ValueError("新闻时间必须包含时区")
        if not isinstance(row["tags"], list) or len(json.dumps(row["tags"], ensure_ascii=False).encode()) > 16384:
            raise ValueError("新闻分类无效")
        if not isinstance(row["url"], str) or len(row["url"]) > 2048:
            raise ValueError("新闻来源链接过长")
        clean.append(dict(row))
    ids = [row["news_id"] for row in clean]
    if any(a <= b for a, b in zip(ids, ids[1:])):
        raise ValueError("新闻 ID 重复或未按倒序排列")
    return {"page": page, "rows": clean, "row_count": len(clean)}


def canonical_payload(envelope, normalized):
    return {"page": normalized["page"], "rows": normalized["rows"]}


def write(connection, envelope, data):
    values = []
    confirmed = []
    observed = mysql_time(envelope.observed_at)
    for row in data["rows"]:
        values.append({**row, "source": envelope.source,
                       "published_at": mysql_time(datetime.fromisoformat(row["published_at"])),
                       "source_updated_at": mysql_time(datetime.fromisoformat(row["source_updated_at"])),
                       "tags": json.dumps(row["tags"], ensure_ascii=False), "observed": observed})
    processed = len(values)
    if values:
        # Compare a bounded page under the same transaction. Observation-only changes
        # must not issue DML; retain source version changes to reject stale replays.
        existing = connection.execute(text("""
            SELECT * FROM finance_news WHERE source=:source AND news_id IN :ids FOR UPDATE
        """).bindparams(bindparam("ids", expanding=True)),
            {"source": envelope.source, "ids": [v["news_id"] for v in values]}).mappings()
        previous = {r["news_id"]: dict(r) for r in existing}
        changed = []
        for value in values:
            old = previous.get(value["news_id"])
            if old is not None:
                old["tags"] = json.loads(old["tags"]) if isinstance(old["tags"], str) else old["tags"]
                if (value["source_updated_at"], observed) < (old["source_updated_at"], old["version_observed_at"]):
                    continue
                if all((json.loads(value[k]) if k == "tags" else value[k]) == old[k]
                       for k in data["rows"][0]):
                    confirmed.append(str(value["news_id"]))
                    continue
            confirmed.append(str(value["news_id"]))
            changed.append(value)
        values = changed
    newer = "(VALUES(source_updated_at)>source_updated_at OR (VALUES(source_updated_at)=source_updated_at AND VALUES(version_observed_at)>=version_observed_at))"
    updates = ",".join(f"{field}=IF({newer},VALUES({field}),{field})" for field in (
        "title", "content", "published_at", "is_important", "tags", "url"))
    if values:
        connection.execute(text(f"""
            INSERT INTO finance_news (source,news_id,title,content,published_at,source_updated_at,
                                      is_important,tags,url,first_seen_at,version_observed_at)
            VALUES (:source,:news_id,:title,:content,:published_at,:source_updated_at,
                    :is_important,:tags,:url,:observed,:observed)
            ON DUPLICATE KEY UPDATE {updates},
                source_updated_at=GREATEST(source_updated_at,VALUES(source_updated_at)),
                first_seen_at=LEAST(first_seen_at,VALUES(first_seen_at)),
                version_observed_at=GREATEST(version_observed_at,VALUES(version_observed_at))
        """), values)
    return {"status": "complete", "row_count": processed, "written_count": len(values),
            "skipped_count": processed - len(values), "confirmed": confirmed}


def fingerprint_plan(envelope, data):
    observed = envelope.observed_at.astimezone(UTC).isoformat(timespec="microseconds")
    return FINGERPRINT_NAMESPACE, {str(row["news_id"]): (row, [
        datetime.fromisoformat(row["source_updated_at"]).astimezone(UTC).isoformat(timespec="microseconds"),
        observed,
    ]) for row in data["rows"]}


def fingerprint_subset(data, identities):
    rows = [row for row in data["rows"] if str(row["news_id"]) in identities]
    return {**data, "rows": rows, "row_count": len(rows)}


def archive_state(envelope, data, outcome, previous):
    return {"progress": confirmed_page(envelope, data, previous)}
