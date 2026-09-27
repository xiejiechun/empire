"""Real SQL, exact test namespace; no collector, shared Redis or business writes."""
import copy
import importlib.util
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import event, text

from empire.contracts.download import MiB
from empire.contracts.download_settings import DEFAULTS, recommended_settings
from empire.core.config import load_config
from empire.plugins.infra.mysql_store import make_engine
from empire.plugins.infra.settings import SettingsStore

spec = importlib.util.spec_from_file_location(
    "capacity_migration_integration", Path(__file__).parents[2] / "scripts/migrate_download_capacity.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Explicit integration opt-in required")]

AUTO = {"min_interval_ms": 3200, "proxy_interval_ms": 4200, "total_interval_ms": 800,
        "scaling_mode": "auto", "max_concurrency": 64, "max_rps": 7}
GROUPS = {"sina": {"domains": ["example.test"]}}


@pytest.fixture
def database():
    engine = make_engine(copy.deepcopy(load_config())["mysql"])
    namespace = "empire:test:capacity:" + uuid4().hex
    store = SettingsStore(None, namespace)
    old = {key: value for key, value in DEFAULTS.items() if key in migration.PRE_CAPACITY_KEYS}
    old["buffer_budget_bytes"] = 64 * MiB
    try:
        with engine.begin() as conn:
            store.save_in_transaction(conn, "download", "global", old)
            store.save_in_transaction(conn, "site", "sina", AUTO)
            store.save_in_transaction(conn, "task", "test", {"use_proxy": False})
        yield engine, namespace
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM app_setting WHERE namespace=:namespace"),
                         {"namespace": namespace})
        engine.dispose()


def read_settings(engine, namespace):
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT kind,setting_key,payload,updated_at FROM app_setting "
            "WHERE namespace=:namespace"), {"namespace": namespace})
        return {(kind, key): (json.loads(value) if isinstance(value, str) else value, updated)
                for kind, key, value, updated in rows}


def test_dry_run_then_atomic_migration_and_same_value_zero_dml(database):
    engine, namespace = database
    before = read_settings(engine, namespace)
    report = migration.migrate_database(engine, namespace, GROUPS,
        recommend_devices=100, follow_auto_sites=True)
    assert not report["applied"] and read_settings(engine, namespace) == before
    assert set(report["changed_settings"]) == {"download/global", "site/sina"}
    report = migration.migrate_database(engine, namespace, GROUPS, apply=True,
        recommend_devices=100, follow_auto_sites=True)
    after = read_settings(engine, namespace)
    assert after[("download", "global")][0] == recommended_settings(100)
    assert after[("site", "sina")][0] == {**AUTO, "max_concurrency": 0}
    assert after[("task", "test")] == before[("task", "test")]
    writes = []

    def capture(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            writes.append(statement)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        repeat = migration.migrate_database(engine, namespace, GROUPS, apply=True,
            recommend_devices=100, follow_auto_sites=True)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert repeat["changed_settings"] == [] and writes == []
    assert read_settings(engine, namespace) == after


def test_second_setting_failure_rolls_back_every_change(database):
    engine, namespace = database
    before = read_settings(engine, namespace)

    def fail_site(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE") and parameters.get("kind") == "site":
            raise RuntimeError("simulated second setting failure")

    event.listen(engine, "before_cursor_execute", fail_site)
    try:
        with pytest.raises(RuntimeError, match="second setting"):
            migration.migrate_database(engine, namespace, GROUPS, apply=True,
                recommend_devices=1000, follow_auto_sites=True)
    finally:
        event.remove(engine, "before_cursor_execute", fail_site)
    assert read_settings(engine, namespace) == before


def test_upgrade_without_recommendation_preserves_saved_limits_and_site_rules(database):
    engine, namespace = database
    before = read_settings(engine, namespace)
    migration.migrate_database(engine, namespace, GROUPS, apply=True)
    after = read_settings(engine, namespace)
    assert after[("download", "global")][0]["buffer_budget_bytes"] == 64 * MiB
    assert after[("site", "sina")] == before[("site", "sina")]
    assert after[("task", "test")] == before[("task", "test")]


def test_expansion_and_downshift_only_change_capacity_fields(database):
    engine, namespace = database
    migration.migrate_database(engine, namespace, GROUPS, apply=True,
        recommend_devices=1000, follow_auto_sites=True)
    large = read_settings(engine, namespace)
    assert large[("download", "global")][0] == recommended_settings(1000)
    migration.migrate_database(engine, namespace, GROUPS, apply=True, recommend_devices=100)
    small = read_settings(engine, namespace)
    assert small[("download", "global")][0] == recommended_settings(100)
    assert small[("site", "sina")] == large[("site", "sina")]
    assert small[("task", "test")] == large[("task", "test")]
