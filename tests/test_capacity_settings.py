"""Device planning is a pure capacity recipe, not permission to accelerate a site."""
import copy
import importlib.util
from pathlib import Path

import pytest

from empire.contracts.download import MiB, ResponsePolicy
from empire.contracts.download_settings import (
    DEFAULTS,
    DEVICE_TIERS,
    recommended_settings,
    validate_settings,
)

spec = importlib.util.spec_from_file_location(
    "capacity_migration", Path(__file__).parents[1] / "scripts/migrate_download_capacity.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

EXPECTED = ((100, 128, 512), (200, 256, 1024), (300, 384, 1536),
            (400, 512, 2048), (500, 512, 2048), (600, 640, 2560),
            (700, 768, 3072), (800, 896, 3584), (900, 1024, 4096), (1000, 1024, 4096))


@pytest.mark.parametrize("devices,window,buffer", EXPECTED)
def test_every_tier_is_valid_and_covers_full_stock_window_with_headroom(devices, window, buffer):
    values = recommended_settings(devices)
    assert validate_settings(values) == values
    assert values["planned_exit_devices"] == devices
    assert values["max_parallel_downloads"] == window
    assert values["buffer_budget_bytes"] == buffer * MiB
    reserve = ResponsePolicy(max_body_bytes=values["stock_response_bytes"]).reservation_bytes
    assert values["buffer_budget_bytes"] * 5 >= window * reserve * 6
    assert DEVICE_TIERS == tuple(item[0] for item in EXPECTED)


def test_default_is_one_hundred_tier_and_values_are_monotonic():
    assert recommended_settings(100) == DEFAULTS
    previous = (0, 0)
    for devices in DEVICE_TIERS:
        values = recommended_settings(devices)
        current = values["max_parallel_downloads"], values["buffer_budget_bytes"]
        assert all(a >= b for a, b in zip(current, previous))
        previous = current


@pytest.mark.parametrize("invalid", [True, False, 0, 99, 101, 150, 1001, 1100, 100.0, "100", None])
def test_only_ten_exact_integer_tiers_are_accepted(invalid):
    with pytest.raises(ValueError):
        recommended_settings(invalid)
    with pytest.raises(ValueError):
        validate_settings({**DEFAULTS, "planned_exit_devices": invalid})


def test_recommendation_preserves_custom_response_and_file_settings_without_mutation():
    current = {**DEFAULTS, "stock_response_bytes": 2 * MiB,
               "file_concurrency": 8, "file_response_bytes": 512 * MiB,
               "download_quota_bytes": 4096 * MiB}
    before = copy.deepcopy(current)
    values = recommended_settings(100, current)
    assert values["buffer_budget_bytes"] == 1024 * MiB
    for key in current.keys() - migration.CAPACITY_KEYS - {"buffer_budget_bytes"}:
        assert values[key] == current[key]
    assert current == before and values is not current
    with pytest.raises(ValueError, match="超过 4096"):
        recommended_settings(1000, current)
    assert current == before


def test_recipe_respects_large_sequential_response_workspace():
    current = {**DEFAULTS, "news_response_bytes": 256 * MiB,
               "buffer_budget_bytes": 1024 * MiB}
    values = recommended_settings(100, current)
    needed = (128 * ResponsePolicy(max_body_bytes=MiB).reservation_bytes
              + ResponsePolicy(max_body_bytes=256 * MiB).reservation_bytes)
    assert values["buffer_budget_bytes"] >= needed


def test_runtime_refuses_old_schema_but_explicit_migration_preserves_existing_values():
    old = {key: value for key, value in DEFAULTS.items() if key in migration.PRE_CAPACITY_KEYS}
    old["buffer_budget_bytes"] = 64 * MiB
    with pytest.raises(ValueError, match="显式迁移"):
        validate_settings(old)
    migrated = migration.upgrade_download_settings(old)
    assert migrated == {**old, "planned_exit_devices": 100, "max_parallel_downloads": 128}
    assert len(old) == 9


@pytest.mark.parametrize("malformed", [None, {}, {"buffer_budget_bytes": 64 * MiB},
    {**DEFAULTS, "unexpected": 1}, {**DEFAULTS, "planned_exit_devices": 150}])
def test_migration_never_silently_repairs_corrupt_configuration(malformed):
    with pytest.raises(ValueError):
        migration.upgrade_download_settings(malformed)


def test_plan_explicitly_changes_only_auto_site_ceiling_and_download_capacity():
    auto = {"scaling_mode": "auto", "max_concurrency": 64, "min_interval_ms": 3200,
            "proxy_interval_ms": 4400, "total_interval_ms": 800, "max_rps": 13}
    fixed = {**auto, "scaling_mode": "fixed"}
    rows = {("download", "global"): dict(DEFAULTS),
            ("site", "auto"): auto, ("site", "fixed"): fixed,
            ("task", "sina-stocks"): {"use_proxy": False}}
    before = copy.deepcopy(rows)
    groups = {"auto": {"domains": ["example.test"]}, "fixed": {"domains": ["other.test"]}}
    changes, values, sites = migration.capacity_plan(rows, groups,
        recommend_devices=1000, follow_auto_sites=True)
    assert changes[("site", "auto")] == {**auto, "max_concurrency": 0}
    assert set(changes) == {("download", "global"), ("site", "auto")}
    assert sites == ["auto"] and values == recommended_settings(1000)
    assert rows == before
    changes, _, _ = migration.capacity_plan(rows, groups, recommend_devices=1000)
    assert set(changes) == {("download", "global")}


def test_plan_is_repeatable_and_existing_following_sites_need_no_update():
    rows = {("download", "global"): recommended_settings(100),
            ("site", "sina"): {"scaling_mode": "auto", "max_concurrency": 0}}
    changes, _, sites = migration.capacity_plan(rows, {"sina": {}},
        recommend_devices=100, follow_auto_sites=True)
    assert changes == {} and sites == []


def test_cli_lock_failure_happens_before_database_or_mutation(monkeypatch):
    cfg = {"http": {}, "redis": {"namespace": "empire:test"}, "mysql": {}, "rate_groups": {}}
    monkeypatch.setattr(migration, "load_config", lambda _: cfg)

    def locked():
        raise RuntimeError("Empire 已运行")

    def unexpected_engine(*_):
        pytest.fail("database must not be opened while Empire holds lock")

    monkeypatch.setattr(migration, "acquire_instance_lock", locked)
    monkeypatch.setattr(migration, "make_engine", unexpected_engine)
    monkeypatch.setattr("sys.argv", ["migrate_download_capacity.py", "--apply"])
    with pytest.raises(SystemExit, match="已运行"):
        migration.main()


def test_cli_failure_is_redacted_and_releases_lock(monkeypatch):
    cfg = {"http": {}, "redis": {"namespace": "empire:test"},
           "mysql": {"password": "migration-secret"}, "rate_groups": {}}
    events = []

    class Lock:
        def unlock(self):
            events.append("unlock")

    def fail_engine(*_):
        raise RuntimeError("connection migration-secret failed")

    monkeypatch.setattr(migration, "load_config", lambda _: cfg)
    monkeypatch.setattr(migration, "acquire_instance_lock", Lock)
    monkeypatch.setattr(migration, "make_engine", fail_engine)
    monkeypatch.setattr("sys.argv", ["migrate_download_capacity.py", "--apply"])
    with pytest.raises(SystemExit) as error:
        migration.main()
    assert "migration-secret" not in str(error.value) and events == ["unlock"]
