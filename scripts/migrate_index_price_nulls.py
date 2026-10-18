"""Explicit nullable source-price migration; never invoked at startup."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from create_index_price_schema import inventory
from sqlalchemy import inspect, text

from empire.__main__ import acquire_instance_lock
from empire.core.config import load_config, project_root
from empire.core.redaction import redact
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.schema_manifest import validate_shapes


def contents(conn):
    """Stream stable business content; no unbounded daily-row materialization."""
    result = inventory(conn)
    for table, order in (("index_daily_price", "index_code,trade_date"),
                         ("index_price_year", "index_code,quote_year")):
        digest, count = hashlib.sha256(), 0
        with conn.execution_options(stream_results=True).execute(
            text(f"SELECT * FROM {table} ORDER BY {order}")
        ) as rows:
            for row in rows:
                digest.update(json.dumps(list(row), default=str, separators=(",", ":")).encode())
                digest.update(b"\n")
                count += 1
        result[table] = dict(rows=count, content_hash=digest.hexdigest())
    return result


def migrate(conn):
    columns = {r["name"]: r for r in inspect(conn).get_columns("index_daily_price")}
    if all(columns[k]["nullable"] for k in ("open", "high", "low")):
        validate_shapes(conn, ("index_daily_price", "index_price_year"))
        return False
    if any(columns[k]["nullable"] for k in ("open", "high", "low")):
        raise RuntimeError("价格列处于未知中间结构，拒绝迁移")
    sql = (project_root() / "sql/schema.sql").read_text("utf8")
    table = sql[sql.index("CREATE TABLE IF NOT EXISTS index_daily_price ("):].split(";", 1)[0]
    check = next(line.strip().rstrip(",") for line in table.splitlines()
                 if "CONSTRAINT ck_index_price_ohlc " in line)
    conn.exec_driver_sql(
        "ALTER TABLE index_daily_price DROP CHECK ck_index_price_ohlc, "
        "MODIFY open DECIMAL(18,6) NULL, MODIFY high DECIMAL(18,6) NULL, "
        "MODIFY low DECIMAL(18,6) NULL, ADD " + check
    )
    conn.commit()
    validate_shapes(conn, ("index_daily_price", "index_price_year"))
    return True


async def run(args, migrate_fn=migrate):
    cfg = load_config(args.config)
    lock = acquire_instance_lock() if args.apply else None
    engine, redis = make_engine(cfg["mysql"]), create_client(cfg["redis"])
    report = dict(applied=False)
    try:
        pending = await redis.xlen(cfg["redis"].get("namespace", "empire") + ":ingest")
        report["pending"] = pending
        with engine.connect() as conn:
            if args.apply:
                if pending:
                    raise RuntimeError("待归档必须清零，拒绝修改结构")
                if conn.execute(text("SELECT GET_LOCK('empire-business-schema-v2',0)")).scalar_one() != 1:
                    raise RuntimeError("另有SQL维护操作")
                try:
                    report["before"] = contents(conn)
                    report["changed"] = migrate_fn(conn)
                    report["after"] = contents(conn)
                    if report["before"] != report["after"]:
                        raise RuntimeError("已有业务内容或状态发生变化，停止交付")
                    report.update(applied=True, existing_business_unchanged=True)
                finally:
                    conn.execute(text("SELECT RELEASE_LOCK('empire-business-schema-v2')"))
            else:
                report["before"] = contents(conn)
    finally:
        if args.report:
            Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf8")
        engine.dispose()
        await redis.aclose()
        if lock:
            lock.unlock()
    print(json.dumps({k: v for k, v in report.items() if k not in ("before", "after")}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    try:
        asyncio.run(run(args))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
