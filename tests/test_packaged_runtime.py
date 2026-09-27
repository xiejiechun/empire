import json
from pathlib import Path

import pytest

from empire import build_info
from empire.core import config


def test_project_root_uses_source_checkout_when_not_frozen() -> None:
    assert config.project_root() == Path(__file__).resolve().parents[1]


def test_resource_root_uses_bundled_directory_when_frozen(monkeypatch) -> None:
    bundled = Path("D:/portable/Empire/_internal")
    monkeypatch.setattr(config.sys, "frozen", True, raising=False)
    monkeypatch.setattr(config.sys, "_MEIPASS", str(bundled), raising=False)

    assert config.resource_root() == bundled
    with pytest.raises(RuntimeError, match="unavailable"):
        config.project_root()


def test_build_manifest_is_strict_and_identifies_dirty_artifacts(tmp_path, monkeypatch) -> None:
    manifest = tmp_path / "build_manifest.json"
    value = {"version": "0.1.0", "commit": "a" * 40, "dirty": True,
             "requirements_sha256": "b" * 64, "built_at_utc": "2026-09-27T00:00:00Z",
             "python": "3.12.9", "pyinstaller": "6.22.3", "dependency_count": 41,
             "dependency_report_sha256": "c" * 64}
    manifest.write_text(json.dumps(value), encoding="utf-8")
    assert build_info.load_build_info(manifest) == {**value, "packaged": True}
    value["unexpected"] = True
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid Empire build manifest"):
        build_info.load_build_info(manifest)
    value.pop("unexpected")
    monkeypatch.setattr(build_info, "load_build_info", lambda: {**value, "packaged": True})
    assert build_info.build_identity() == "0.1.0 (aaaaaaaaaaaa+dirty)"
    assert "含未提交修改" in build_info.build_summary()[0]


def test_source_build_identity_is_explicitly_development() -> None:
    value = build_info.load_build_info(Path("missing-build-manifest.json"))
    assert value["commit"] == "development" and not value["packaged"]


def test_package_contains_all_runtime_owned_resources() -> None:
    spec = (Path(__file__).resolve().parents[1] / "Empire.spec").read_text(encoding="utf-8")
    assert '"config" / "app.example.toml"' in spec
    assert '"sql" / "schema.sql"' in spec
    assert '"dependency-report.json"' in spec
