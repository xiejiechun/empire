import json
from pathlib import Path

import pytest

from empire import build_info
from empire.core import config


def manifest_value():
    return {"version": "0.1.0", "commit": "a" * 40, "dirty": True,
            "requirements_sha256": "b" * 64, "built_at_utc": "2026-09-27T00:00:00Z",
            "python": "3.12.9", "pyinstaller": "6.22.3", "dependency_count": 41,
            "dependency_report_sha256": "c" * 64, "source_sha256": "d" * 64,
            "release_id": "e" * 32}


def write_manifest(tmp_path, value):
    manifest = tmp_path / "build_manifest.json"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    return manifest


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
    value = manifest_value()
    manifest = write_manifest(tmp_path, value)
    assert build_info.load_build_info(manifest) == {**value, "packaged": True}
    value["unexpected"] = True
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid Empire build manifest"):
        build_info.load_build_info(manifest)
    value.pop("unexpected")
    monkeypatch.setattr(build_info, "load_build_info", lambda: {**value, "packaged": True})
    assert build_info.build_identity() == "0.1.0 (aaaaaaaaaaaa+dirty)"
    summary, detail = build_info.build_summary()
    assert "含未提交修改" in summary
    assert "发布 ID：" + value["release_id"] in detail
    assert "源输入 SHA-256：" + value["source_sha256"] in detail
    value["dirty"] = False
    assert build_info.build_identity() == "0.1.0 (aaaaaaaaaaaa)"
    assert "干净提交" in build_info.build_summary()[0]




@pytest.mark.parametrize("missing", tuple(manifest_value()))
def test_packaged_manifest_rejects_each_missing_current_field(tmp_path, missing):
    value = manifest_value()
    value.pop(missing)
    with pytest.raises(ValueError, match="Invalid Empire build manifest"):
        build_info.load_build_info(write_manifest(tmp_path, value))


def test_old_manifest_field_set_is_not_a_runtime_compatibility_path(tmp_path):
    value = manifest_value()
    value.pop("source_sha256")
    value.pop("release_id")
    with pytest.raises(ValueError, match="Invalid Empire build manifest"):
        build_info.load_build_info(write_manifest(tmp_path, value))


@pytest.mark.parametrize("field,invalid", (
    ("version", "different"), ("dirty", 1), ("dependency_count", True),
    ("dependency_count", -1), ("dependency_count", 1.5), ("built_at_utc", None),
    ("python", []), ("pyinstaller", ""), ("source_sha256", 123), ("release_id", False),
))
def test_packaged_manifest_rejects_invalid_metadata_types(tmp_path, field, invalid):
    value = {**manifest_value(), field: invalid}
    with pytest.raises(ValueError, match="Inconsistent Empire build manifest"):
        build_info.load_build_info(write_manifest(tmp_path, value))


@pytest.mark.parametrize("field", ("source_sha256", "requirements_sha256", "dependency_report_sha256"))
@pytest.mark.parametrize("invalid", ("a" * 63, "a" * 65, "g" * 64, "A" * 64))
def test_packaged_manifest_rejects_noncanonical_sha256(tmp_path, field, invalid):
    with pytest.raises(ValueError, match="Invalid Empire build manifest identity"):
        build_info.load_build_info(write_manifest(tmp_path, {**manifest_value(), field: invalid}))


@pytest.mark.parametrize("field,invalid", (
    ("commit", "a" * 39), ("commit", "a" * 41), ("commit", "g" * 40), ("commit", "A" * 40),
    ("release_id", "e" * 31), ("release_id", "e" * 33), ("release_id", "g" * 32),
    ("release_id", "E" * 32), ("release_id", "../" + "e" * 29),
))
def test_packaged_manifest_rejects_noncanonical_commit_or_release_id(tmp_path, field, invalid):
    with pytest.raises(ValueError, match="Invalid Empire build manifest identity"):
        build_info.load_build_info(write_manifest(tmp_path, {**manifest_value(), field: invalid}))


def test_source_build_identity_is_explicitly_development() -> None:
    value = build_info.load_build_info(Path("missing-build-manifest.json"))
    assert value["commit"] == "development" and not value["packaged"]
    assert value["source_sha256"] == value["release_id"] == ""


def test_packaged_runtime_cannot_fall_back_to_development_without_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(build_info.sys, "frozen", True, raising=False)
    with pytest.raises(ValueError, match="Missing Empire build manifest"):
        build_info.load_build_info(tmp_path / "missing-build-manifest.json")
