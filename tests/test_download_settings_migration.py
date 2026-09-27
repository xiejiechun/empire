"""Migration tests use temporary configuration files and an in-memory SQL double."""
import copy
import importlib.util
import tomllib
from pathlib import Path

import pytest

from empire.contracts.download_settings import DEFAULTS, LEGACY_KEYS

spec = importlib.util.spec_from_file_location(
    "download_settings_migration", Path(__file__).parents[1] / "scripts/migrate_download_settings.py")
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

SOURCE = '''# local configuration\r
[mysql]\r
user = "empire"\r
password = 'private@pass#word' # preserve credentials and comment\r
database = "test"\r
[redis]\r
namespace = "empire:test-migration"\r
[http] # directory remains local\r
buffer_budget_bytes = 100_663_296 # buffer comment\r
download_quota_bytes = 2147483648\r
disk_free_margin_bytes = 134217728\r
file_concurrency = 4\r
download_directory = 'D:\\Downloads' # preserve directory\r
[other]\r
value = "preserve me"\r
'''


@pytest.fixture
def environment(tmp_path, monkeypatch):
    path = tmp_path / "local.toml"
    path.write_bytes(SOURCE.encode("utf-8"))
    state = {"value": None, "saves": [], "loads": 0, "starts": 0, "stops": 0,
             "locks": 0, "unlocks": 0, "failure": None, "after_save": None,
             "stored_null": False}

    class Lock:
        def unlock(self):
            state["unlocks"] += 1

    def acquire():
        state["locks"] += 1
        return Lock()

    class Mysql:
        def __init__(self, settings):
            self.settings = settings

        async def start(self, context):
            assert context is None
            state["starts"] += 1

        async def stop(self):
            state["stops"] += 1

    class Store:
        def __init__(self, mysql, namespace):
            assert namespace == "empire:test-migration"

        async def load(self, kind):
            assert kind == "download"
            state["loads"] += 1
            if state["value"] is None and not state["stored_null"]:
                return {}
            return {"global": copy.deepcopy(state["value"])}

        async def save(self, kind, key, value):
            assert (kind, key) == ("download", "global")
            if state["failure"]:
                raise state["failure"]
            state["saves"].append(copy.deepcopy(value))
            state["value"] = copy.deepcopy(value)
            if state["after_save"]:
                state["after_save"]()

    monkeypatch.setattr(migration, "acquire_instance_lock", acquire)
    monkeypatch.setattr(migration, "MySQLPlugin", Mysql)
    monkeypatch.setattr(migration, "SettingsStore", Store)
    return path, state


def test_plan_preserves_other_content_comments_credentials_and_line_endings():
    old, rewritten, values, keys = migration.migration_plan(SOURCE)
    expected = copy.deepcopy(old)
    for key in LEGACY_KEYS:
        del expected["http"][key]
    assert tomllib.loads(rewritten) == expected
    assert "password = 'private@pass#word' # preserve credentials and comment\r\n" in rewritten
    assert "# buffer comment\r\n" in rewritten
    assert "download_directory = 'D:\\Downloads' # preserve directory\r\n" in rewritten
    assert keys == sorted(LEGACY_KEYS)
    assert values == {**DEFAULTS, "buffer_budget_bytes": 96 * 1024 * 1024}


@pytest.mark.parametrize("source", [
    'http = { buffer_budget_bytes = 100663296 }\n',
    'http.buffer_budget_bytes = 100663296\n',
    '["http"]\nbuffer_budget_bytes = 100663296\n',
    '[http]\n"buffer_budget_bytes" = 100663296\n',
    '[http]\nbuffer_budget_bytes = 0x06000000\n',
])
def test_complex_toml_is_refused_without_mutation(source):
    with pytest.raises(ValueError, match="复杂 TOML"):
        migration.migration_plan(source)


@pytest.mark.parametrize("value", ["true", "0", "-1", '"100663296"'])
def test_invalid_legacy_values_fail_validation(value):
    with pytest.raises(ValueError):
        migration.migration_plan(f"[http]\nbuffer_budget_bytes = {value}\n")


async def test_dry_run_locks_and_compares_sql_without_writes(environment):
    path, state = environment
    before = path.read_bytes()
    report = await migration.migrate(path)
    assert report["applied"] is False
    assert state["loads"] == 1 and not state["saves"]
    assert path.read_bytes() == before
    assert state["locks"] == state["unlocks"] == 1
    assert state["starts"] == state["stops"] == 1


async def test_apply_persists_then_retires_old_keys_and_is_repeatable(environment):
    path, state = environment
    first = await migration.migrate(path, apply=True)
    rewritten = path.read_bytes()
    second = await migration.migrate(path, apply=True)
    assert first["applied"] is True and second["status"] == "无需迁移"
    assert len(state["saves"]) == 1 and state["starts"] == 1
    assert not set(tomllib.loads(rewritten.decode())["http"]) & set(LEGACY_KEYS)
    assert path.read_bytes() == rewritten
    assert state["locks"] == state["unlocks"] == 2
    assert not list(path.parent.glob(".download-settings-*.tmp"))


@pytest.mark.parametrize("apply", [False, True])
async def test_different_existing_sql_is_never_overwritten(environment, apply):
    path, state = environment
    state["value"] = dict(DEFAULTS)
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="拒绝覆盖"):
        await migration.migrate(path, apply=apply)
    assert path.read_bytes() == before and not state["saves"]
    assert state["stops"] == state["unlocks"] == 1


async def test_same_existing_sql_finishes_file_retirement_without_rewriting_sql(environment):
    path, state = environment
    state["value"] = migration.migration_plan(SOURCE)[2]
    result = await migration.migrate(path, apply=True)
    assert result["applied"] is True and not state["saves"]


async def test_malformed_existing_sql_null_is_not_treated_as_missing(environment):
    path, state = environment
    state["stored_null"] = True
    with pytest.raises(RuntimeError, match="拒绝覆盖"):
        await migration.migrate(path, apply=True)
    assert path.read_bytes() == SOURCE.encode() and not state["saves"]


async def test_sql_failure_preserves_complete_local_file(environment):
    path, state = environment
    state["failure"] = RuntimeError("database unavailable")
    before = path.read_bytes()
    with pytest.raises(RuntimeError, match="database unavailable"):
        await migration.migrate(path, apply=True)
    assert path.read_bytes() == before
    assert state["stops"] == state["unlocks"] == 1
    assert not list(path.parent.glob(".download-settings-*.tmp"))


async def test_replace_failure_can_resume_after_sql_commit(environment, monkeypatch):
    path, state = environment
    before = path.read_bytes()
    original_replace = migration.os.replace

    def fail_replace(source, target):
        raise OSError("file busy")

    monkeypatch.setattr(migration.os, "replace", fail_replace)
    with pytest.raises(OSError, match="file busy"):
        await migration.migrate(path, apply=True)
    assert path.read_bytes() == before and len(state["saves"]) == 1
    assert not list(path.parent.glob(".download-settings-*.tmp"))
    monkeypatch.setattr(migration.os, "replace", original_replace)
    await migration.migrate(path, apply=True)
    assert len(state["saves"]) == 1


async def test_file_changed_after_commit_is_not_overwritten(environment):
    path, state = environment
    changed = (SOURCE + "# concurrent edit\r\n").encode()
    state["after_save"] = lambda: path.write_bytes(changed)
    with pytest.raises(RuntimeError, match="迁移期间变化"):
        await migration.migrate(path, apply=True)
    assert path.read_bytes() == changed and len(state["saves"]) == 1


async def test_failed_sql_readback_preserves_local_configuration(environment):
    path, state = environment
    state["after_save"] = lambda: state.update(value={})
    with pytest.raises(RuntimeError, match="回读不一致"):
        await migration.migrate(path, apply=True)
    assert path.read_bytes() == SOURCE.encode()


async def test_running_empire_lock_failure_stops_before_sql(environment, monkeypatch):
    path, state = environment

    def locked():
        raise RuntimeError("Empire 已运行")

    monkeypatch.setattr(migration, "acquire_instance_lock", locked)
    with pytest.raises(RuntimeError, match="已运行"):
        await migration.migrate(path, apply=True)
    assert state["starts"] == 0 and path.read_bytes() == SOURCE.encode()


def test_cli_redacts_credentials(environment, monkeypatch):
    path, _ = environment

    async def fail(*args, **kwargs):
        raise RuntimeError("connection refused private@pass#word")

    monkeypatch.setattr(migration, "migrate", fail)
    monkeypatch.setattr("sys.argv", ["migrate_download_settings.py", "--config", str(path)])
    with pytest.raises(SystemExit) as result:
        migration.main()
    assert "private@pass#word" not in str(result.value)


def test_environment_password_override_only_changes_connection_copy(monkeypatch):
    original = tomllib.loads(SOURCE)
    monkeypatch.setenv("EMPIRE_MYSQL_PASSWORD", "environment-only")
    connected = migration.connection_config(original)
    assert connected["mysql"]["password"] == "environment-only"
    assert original["mysql"]["password"] == "private@pass#word"
