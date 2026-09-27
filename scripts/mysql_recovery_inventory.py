"""Create or compare a read-only MySQL recovery inventory.

The command never creates, drops, or changes tables. A restored-database check is
accepted only for a different database whose name ends in ``_restore_drill``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import inspect, text

from empire.core.config import load_config
from empire.core.redaction import redact
from empire.plugins.infra.mysql_store import make_engine

TABLES = {
    "stock": ("source", "unified_code"),
    "finance_news": ("source", "news_id"),
    "trade_calendar": ("source", "trade_date"),
    "collection_state": ("namespace", "project_id"),
    "app_setting": ("namespace", "kind", "setting_key"),
}


def file_identity(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    if not path.is_file():
        raise ValueError(f"Backup file does not exist: {path}")
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"name": path.name, "size_bytes": size, "sha256": digest.hexdigest()}


def schema_identity(metadata: Any, table: str) -> dict[str, Any]:
    indexes = [{"name": value.get("name"), "unique": bool(value.get("unique")),
                "columns": list(value.get("column_names") or [])}
               for value in metadata.get_indexes(table)]
    indexes.sort(key=lambda value: (str(value["name"]), value["columns"]))
    return {
        "columns": [{"name": value["name"], "type": str(value["type"]),
                     "nullable": bool(value.get("nullable")),
                     "default": str(value["default"]) if value.get("default") is not None else None}
                    for value in metadata.get_columns(table)],
        "primary_key": list(metadata.get_pk_constraint(table).get("constrained_columns") or []),
        "indexes": indexes,
        "engine": str(metadata.get_table_options(table).get("mysql_engine", "")).lower(),
    }


def table_identity(connection: Any, table: str, order: tuple[str, ...]) -> dict[str, Any]:
    digest = hashlib.sha256()
    rows = 0
    query = text(f"SELECT * FROM `{table}` ORDER BY "
                 + ",".join(f"`{column}`" for column in order))
    for row in connection.execution_options(stream_results=True).execute(query):
        payload = json.dumps(list(row), default=str, ensure_ascii=False,
                             separators=(",", ":")).encode("utf-8")
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
        rows += 1
    return {"rows": rows, "sha256": digest.hexdigest()}


def collect_inventory(settings: dict[str, Any], backup: Path | None = None) -> dict[str, Any]:
    engine = make_engine(settings, pool_size=1)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            try:
                metadata = inspect(connection)
                existing = set(metadata.get_table_names())
                missing = sorted(set(TABLES) - existing)
                if missing:
                    raise RuntimeError(f"Recovery inventory is missing tables: {missing}")
                tables = {
                    name: {"schema": schema_identity(metadata, name),
                           "content": table_identity(connection, name, order)}
                    for name, order in TABLES.items()
                }
                version = str(connection.execute(text("SELECT VERSION()" )).scalar_one())
            finally:
                connection.rollback()
    finally:
        engine.dispose()
    return {
        "schema_version": 1,
        "captured_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "database": settings["database"],
        "server": {"host": settings.get("host", "127.0.0.1"),
                   "port": int(settings.get("port", 3306)), "version": version},
        "transaction": "read-only consistent snapshot",
        "tables": tables,
        "backup": file_identity(backup),
    }


def compare_inventory(baseline: dict[str, Any], restored: dict[str, Any]) -> dict[str, Any]:
    source_database = baseline.get("database")
    restored_database = restored.get("database")
    if not isinstance(restored_database, str) or not restored_database.endswith("_restore_drill"):
        raise ValueError("Restored database name must end with _restore_drill")
    if restored_database == source_database:
        raise ValueError("Recovery verification cannot target the source database")
    differences = []
    for table in TABLES:
        expected = baseline.get("tables", {}).get(table)
        actual = restored.get("tables", {}).get(table)
        if expected != actual:
            differences.append({"table": table, "expected": expected, "actual": actual})
    return {
        "schema_version": 1,
        "verified_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "source_database": source_database,
        "restored_database": restored_database,
        "tables_checked": list(TABLES),
        "differences": differences,
        "passed": not differences,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True,
                        help="Source or isolated restore TOML configuration")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--backup-file", type=Path,
                        help="Optional dump file whose size and SHA-256 are recorded")
    parser.add_argument("--compare", type=Path,
                        help="Baseline inventory; enables strict restored-database comparison")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    try:
        inventory = collect_inventory(config["mysql"], args.backup_file)
        result = compare_inventory(
            json.loads(args.compare.read_text(encoding="utf-8")), inventory
        ) if args.compare else inventory
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
        print(f"{'PASS' if result.get('passed', True) else 'FAIL'} recovery inventory: {args.output}")
        return 0 if result.get("passed", True) else 1
    except Exception as exc:
        raise SystemExit(redact(exc, config)) from None


if __name__ == "__main__":
    raise SystemExit(main())
