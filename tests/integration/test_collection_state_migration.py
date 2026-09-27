"""Migration checks in UUID-owned tables, never business tables."""
import importlib.util
import json
import os
import re
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine

spec = importlib.util.spec_from_file_location(
    "collection_state_migration", Path(__file__).parents[2] / "scripts/migrate_collection_state.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Explicit integration opt-in required")]


def test_migration_preserves_rows_versions_and_is_repeatable():
    settings = dict(load_config()["mysql"])
    engine = make_engine(settings)
    names = {name: "test_" + uuid4().hex + "_" + name for name in (
        "stock", "stock_publication", "collection_state", "finance_news", "trade_calendar", "app_setting")}
    pattern = re.compile(r"\b(" + "|".join(names) + r")\b")

    def isolate(conn, cursor, statement, parameters, context, executemany):
        return pattern.sub(lambda m: names[m.group()], statement), parameters

    event.listen(engine, "before_cursor_execute", isolate, retval=True)
    try:
        schema = (Path(__file__).parents[2] / "sql/schema.sql").read_text(encoding="utf-8")
        schema = "\n".join(line for line in schema.splitlines() if not line.startswith("--"))
        with engine.begin() as conn:
            for statement in schema.split(";"):
                if statement.strip():
                    conn.execute(text(statement))
            conn.execute(text("CREATE TABLE stock_publication (source VARCHAR(80) PRIMARY KEY, "
                "generation CHAR(32) NOT NULL, started_at DATETIME(6) NOT NULL, "
                "collected_at DATETIME(6) NOT NULL,row_count INT NOT NULL) ENGINE=InnoDB"))
            conn.execute(text("""
                INSERT INTO stock VALUES('sina','hs_a','000001.SZ','000001','测试','SZ','sz000001')
            """))
            conn.execute(text("""
                INSERT INTO stock_publication VALUES('sina',:id,'2026-09-26 12:00:00','2026-09-26 12:01:00',1)
            """), {"id": "a" * 32})
            conn.execute(text("""
                INSERT INTO finance_news VALUES('sina',1,'标题','内容','2026-09-26 12:00:00',
                '2026-09-26 12:00:00',0,'[]','https://finance.sina.com.cn/',
                '2026-09-26 12:01:00','2026-09-26 12:02:00')
            """))
            conn.execute(text("INSERT INTO trade_calendar VALUES('cninfo','2026-09-26',0,'2026-09-26 12:00:00')"))
        first = migration.migrate_schema(engine, "test", {
            "cninfo-calendar": {"observed": {"2026-09": "2026-09-26T03:00:00+00:00"}}})
        second = migration.migrate_schema(engine, "test")
        assert first["before"] == first["after"] == second["after"]
        with engine.connect() as conn:
            rows = conn.execute(text("SELECT project_id,payload FROM collection_state")).all()
            assert len(rows) == 3 and first["retired_stock_publication"]
            assert not second["retired_stock_publication"]
            value = json.loads(dict(rows)["sina-stocks"])["publication"]
            assert value["row_count"] == 1 and value["snapshot_id"] == "a" * 32
            assert value["finished_at"] == "2026-09-26T12:01:00"
            observed = json.loads(dict(rows)["cninfo-calendar"])["observed"]
            assert observed["2026-09"] == "2026-09-26T04:00:00.000000+00:00"
    finally:
        event.remove(engine, "before_cursor_execute", isolate)
        with engine.begin() as conn:
            for name in names.values():
                conn.execute(text(f"DROP TABLE IF EXISTS `{name}`"))
        engine.dispose()
