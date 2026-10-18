"""Explicitly preserve signed source volume/amount; no startup migration."""

import argparse
import asyncio

from migrate_index_price_nulls import run
from sqlalchemy import inspect

from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.schema_manifest import normalize_check, validate_shapes


def migrate(conn):
    checks = {r["name"]: normalize_check(r["sqltext"])
              for r in inspect(conn).get_check_constraints("index_daily_price")}
    old = checks.get("ck_index_price_volume")
    if old is None:
        validate_shapes(conn, ("index_daily_price", "index_price_year"))
        return False
    if old != "((volume>=0)and((amountisnull)or(amount>=0)))":
        raise RuntimeError("未知量额约束，拒绝迁移")
    conn.exec_driver_sql("ALTER TABLE index_daily_price DROP CHECK ck_index_price_volume")
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
