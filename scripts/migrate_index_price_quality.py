"""Explicit source OHLC quality contract migration; no business value changes."""

import argparse
import asyncio

from migrate_index_price_nulls import run
from sqlalchemy import inspect

from empire.core.config import load_config, project_root
from empire.core.redaction import redact
from empire.plugins.infra.schema_manifest import validate_shapes


def migrate(conn):
    columns = {r["name"]: r for r in inspect(conn).get_columns("index_daily_price")}
    if not all(columns[k]["nullable"] for k in ("open", "high", "low")):
        raise RuntimeError("先通过显式缺失价格迁移建立现行NULL契约")
    checks = {r["name"]: r["sqltext"] for r in inspect(conn).get_check_constraints("index_daily_price")}
    current = checks.get("ck_index_price_ohlc", "")
    compact = current.lower().replace("`", "").replace(" ", "").replace("(", "").replace(")", "")
    positive = "close>0andopenisnulloropen>0andhighisnullorhigh>0andlowisnullorlow>0"
    if compact == positive:
        validate_shapes(conn, ("index_daily_price", "index_price_year"))
        return False
    expected = positive + "andlowisnullorhighisnullorlow<=highandlowisnulloropenisnullorlow<=openandhighisnulloropenisnulloropen<=highandlowisnullorlow<=closeandhighisnullorclose<=high"
    if compact != expected:
        raise RuntimeError("未知价格约束，拒绝替换")
    sql = (project_root() / "sql/schema.sql").read_text("utf8")
    table = sql[sql.index("CREATE TABLE IF NOT EXISTS index_daily_price ("):].split(";", 1)[0]
    check = next(line.strip().rstrip(",") for line in table.splitlines()
                 if "CONSTRAINT ck_index_price_ohlc " in line)
    conn.exec_driver_sql("ALTER TABLE index_daily_price DROP CHECK ck_index_price_ohlc, ADD " + check)
    conn.commit()
    validate_shapes(conn, ("index_daily_price", "index_price_year"))
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report")
    args = parser.parse_args()
    try:
        asyncio.run(run(args, migrate))
    except Exception as exc:
        raise SystemExit(redact(exc, load_config(args.config))) from None
