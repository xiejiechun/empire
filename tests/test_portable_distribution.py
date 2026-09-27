import pytest

from empire.core import config
from scripts.migrate_user_config import migrate


def test_default_config_is_created_once_in_user_data_and_requires_edit(tmp_path, monkeypatch):
    user = tmp_path / "用户 数据"
    monkeypatch.setattr(config, "user_data_dir", lambda: user)
    with pytest.raises(config.ConfigurationRequiredError, match="首次运行配置已创建"):
        config.load_config()
    target = user / "config.toml"
    assert target.is_file()
    assert "password = \"\"" in target.read_text(encoding="utf-8")
    loaded = config.load_config()
    assert loaded["_path"] == str(target.resolve())


def test_explicit_missing_config_is_not_silently_created(tmp_path):
    target = tmp_path / "explicit.toml"
    with pytest.raises(ValueError, match="does not exist"):
        config.load_config(target)
    assert not target.exists()


def test_relative_download_directory_is_resolved_from_config_location(tmp_path):
    target = tmp_path / "设置 目录" / "config.toml"
    target.parent.mkdir()
    target.write_text(
        "[redis]\nnamespace='empire:test'\n[archive]\nindex_max_entries=100000\n"
        "[ingest]\nmax_queue_entries=100000\n[http]\ndownload_directory='downloads'\n",
        encoding="utf-8",
    )
    loaded = config.load_config(target)
    assert loaded["http"]["download_directory"] == str((target.parent / "downloads").resolve())


def test_packaged_resources_use_meipass_not_executable_parents(tmp_path, monkeypatch):
    resources = tmp_path / "只读 资源"
    executable = tmp_path / "任意 安装目录" / "Empire.exe"
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "_MEIPASS", str(resources), raising=False)
    monkeypatch.setattr(config.sys, "executable", str(executable))
    assert config.resource_root() == resources.resolve()


def test_user_config_migration_never_overwrites_different_destination(tmp_path):
    source = tmp_path / "legacy.toml"
    destination = tmp_path / "user" / "config.toml"
    source.write_text("secret-source", encoding="utf-8")
    assert migrate(source, destination) == "migrated"
    assert source.read_text(encoding="utf-8") == "secret-source"
    assert migrate(source, destination) == "already-current"
    destination.write_text("different", encoding="utf-8")
    with pytest.raises(RuntimeError, match="refusing to overwrite"):
        migrate(source, destination)
    assert destination.read_text(encoding="utf-8") == "different"
