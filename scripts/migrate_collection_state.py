"""Explicit migration to one SQL-confirmed state per project; never run at startup."""
import asyncio
import hashlib
import json
from datetime import datetime

from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config, project_root
from empire.core.redaction import redact
from empire.core.time import CHINA
from empire.plugins.infra.collection_state import read_state, save_state
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client

PROJECTS = (
    ("sina-stocks", "sina", "stocks", "stock", "sina-universe-v1"),
    ("sina-news", "sina", "news", "finance_news", "sina-news-v1"),
    ("cninfo-calendar", "cninfo", "calendar", "trade_calendar", "cninfo-calendar-v1"),
)


def business_snapshot(engine):
    result = {}
    with engine.connect() as conn:
        for table, order in (("stock", "source,unified_code"), ("finance_news", "source,news_id"),
                             ("trade_calendar", "source,trade_date")):
            digest, count = hashlib.sha256(), 0
            for row in conn.execute(text(f"SELECT * FROM {table} ORDER BY {order}")):
                digest.update(json.dumps(list(row), default=str, ensure_ascii=False).encode())
                count += 1
            result[table] = {"rows": count, "sha256": digest.hexdigest()}
    return result


def migrate_schema(engine, namespace, confirmed=None):
    confirmed = confirmed or {}
    before = business_snapshot(engine)
    with engine.connect() as conn:
        old_exists = inspect(conn).has_table("stock_publication")
        old = list(conn.execute(text("SELECT * FROM stock_publication")).mappings()) if old_exists else []
        if any(row["source"] != "sina" for row in old):
            raise RuntimeError("存在未登记的股票来源，未覆盖或删除发布信息")
        for _, source, _, table, _ in PROJECTS:
            if conn.execute(text(f"SELECT 1 FROM {table} WHERE source<>:source LIMIT 1"),
                            {"source": source}).first():
                raise RuntimeError(f"{table} 存在未登记来源，请核对项目映射")
    schema = (project_root() / "sql/schema.sql").read_text(encoding="utf-8")
    ddl = "CREATE TABLE IF NOT EXISTS collection_state" + schema.split(
        "CREATE TABLE IF NOT EXISTS collection_state", 1)[1].split(";", 1)[0]
    with engine.begin() as conn:
        conn.execute(text(ddl))
    with engine.begin() as conn:
        for project, source, dataset, table, _ in PROJECTS:
            existing = read_state(conn, namespace, project, source, lock=True)
            payload = {"progress": {}}
            if dataset == "stocks":
                if old:
                    row = old[0]
                    publication = {"snapshot_id": row["generation"],
                        "started_at": row["started_at"].isoformat(),
                        "finished_at": row["collected_at"].isoformat(), "row_count": row["row_count"]}
                    payload = {"publication": publication,
                        "version": [row["started_at"].isoformat(timespec="microseconds"), row["generation"]],
                        "progress": {**publication, "status": "complete", "expected_count": row["row_count"],
                                     "error_text": ""}}
                    if existing and existing.get("publication") != publication:
                        raise RuntimeError("新旧股票发布信息不一致，保留旧表")
                elif not existing and before["stock"]["rows"]:
                    raise RuntimeError("已有股票缺少发布依据，停止迁移")
            elif dataset == "calendar":
                observed = {}
                for month, value in conn.execute(text("SELECT DATE_FORMAT(trade_date,'%Y-%m'),MAX(updated_at) "
                        "FROM trade_calendar WHERE source=:source GROUP BY DATE_FORMAT(trade_date,'%Y-%m')"),
                        {"source": source}):
                    from datetime import UTC
                    observed[month] = value.replace(tzinfo=CHINA).astimezone(UTC).isoformat(timespec="microseconds")
                for month, value in confirmed.get(project, {}).get("observed", {}).items():
                    if month not in observed or datetime.fromisoformat(value) > datetime.fromisoformat(observed[month]):
                        observed[month] = value
                payload["observed"] = observed
            progress = confirmed.get(project, {}).get("progress", {})
            if progress.get("status") == "complete":
                payload["progress"] = progress
                if dataset == "stocks" and progress.get("started_at"):
                    payload["version"] = [datetime.fromisoformat(progress["started_at"]).isoformat(
                        timespec="microseconds"), progress["snapshot_id"]]
            if not existing:
                save_state(conn, namespace, project, source, dataset, payload, {})
        stocks = read_state(conn, namespace, "sina-stocks", "sina")
        count = stocks.get("publication", {}).get("row_count", 0)
        if count != before["stock"]["rows"]:
            raise RuntimeError("股票发布条数与业务表不一致，旧表保留")
    after = business_snapshot(engine)
    if before != after:
        raise RuntimeError("业务数据内容核验失败，旧表保留")
    if old_exists:
        with engine.begin() as conn:
            conn.execute(text("DROP TABLE stock_publication"))
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM collection_state WHERE namespace=:namespace"),
                             {"namespace": namespace}).scalar_one()
    return {"before": before, "after": after, "business_unchanged": True,
            "project_rows": count, "retired_stock_publication": old_exists}


async def migrate(cfg):
    lock = acquire_instance_lock()
    engine = make_engine(cfg["mysql"])
    redis = create_client(cfg["redis"])
    namespace = cfg["redis"].get("namespace", "empire:dev")
    try:
        if await redis.xlen(f"{namespace}:ingest"):
            raise RuntimeError("待归档队列非空，请先使用迁移前版本完成归档")
        confirmed = {}
        for project, source, dataset, _, job in PROJECTS:
            key = f"{namespace}:stocks:committed:{source}" if dataset == "stocks" else f"{namespace}:archive:progress:{job}"
            raw = await redis.get(key)
            confirmed[project] = {"progress": json.loads(raw) if raw else {}}
            if dataset == "calendar":
                confirmed[project]["observed"] = await redis.hgetall(f"{namespace}:archive:observed:calendar.month:{source}")
        report = migrate_schema(engine, namespace, confirmed)
        # Calendar version proof now belongs to the unified row/fingerprint cache.
        await redis.delete(f"{namespace}:archive:observed:calendar.month:cninfo")
        report["queued"] = await redis.xlen(f"{namespace}:ingest")
        path = project_root() / "artifacts" / "collection-state-migration.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    finally:
        await redis.aclose()
        engine.dispose()
        lock.unlock()


if __name__ == "__main__":
    config = load_config()
    try:
        asyncio.run(migrate(config))
    except Exception as exc:
        raise SystemExit(redact(exc, config)) from None
