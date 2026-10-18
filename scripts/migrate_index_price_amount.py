"""Explicit nullable source amount migration; preserves all existing business content."""

import argparse
import asyncio

from migrate_index_price_nulls import run
from sqlalchemy import inspect

from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.schema_manifest import normalize_check, validate_shapes


def migrate(conn):
    meta = inspect(conn)
    amount = next(c for c in meta.get_columns("index_daily_price") if c["name"] == "amount")
    if amount["nullable"]:
        validate_shapes(conn, ("index_daily_price", "index_price_year"))
        return False
    checks = {r["name"]: normalize_check(r["sqltext"]) for r in meta.get_check_constraints("index_daily_price")}
    if (str(amount["type"]).replace(" ", "").lower() != "decimal(24,4)"
            or checks.get("ck_index_price_volume") != "((volume>=0)and(amount>=0))"):
        raise RuntimeError("未知成交额结构或约束，拒绝迁移")
    conn.exec_driver_sql("ALTER TABLE index_daily_price DROP CHECK ck_index_price_volume, "
                         "MODIFY amount DECIMAL(24,4) NULL")
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
