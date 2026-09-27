from pathlib import Path

import pytest

from scripts.audit_dependencies import build_inventory
from scripts.verify_release_environment import locked_requirements, verify

_HASH = "0" * 64


def test_release_lock_accepts_only_exact_versions(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text(f"pytest>=9 --hash=sha256:{_HASH}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="one exact version"):
        locked_requirements(lock)
    lock.write_text(
        f"pytest==9.1.1 \\\n  --hash=sha256:{_HASH}\n",
        encoding="utf-8",
    )
    locked = locked_requirements(lock)[0]
    assert str(locked.requirement.specifier) == "==9.1.1"
    assert locked.hashes == (_HASH,)


def test_release_lock_rejects_missing_invalid_and_duplicate_hashes(tmp_path: Path) -> None:
    lock = tmp_path / "requirements.lock"
    lock.write_text("pytest==9.1.1\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="requires a SHA-256"):
        locked_requirements(lock)
    lock.write_text("pytest==9.1.1 --hash=sha256:abcd\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Unsupported release lock option"):
        locked_requirements(lock)
    lock.write_text(
        f"pytest==9.1.1 --hash=sha256:{_HASH}\npytest==9.1.1 --hash=sha256:{'1' * 64}\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="Duplicate release lock package"):
        locked_requirements(lock)


def test_current_release_environment_matches_lock() -> None:
    verify(Path(__file__).resolve().parents[1])


def test_dependency_inventory_matches_current_lock() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_inventory(root)
    assert report["component_count"] == len(locked_requirements(root / "requirements.lock"))
    assert {item["scope"] for item in report["components"]} >= {
        "direct-runtime", "direct-development", "transitive"
    }
    assert all(item["locked_sha256"] for item in report["components"])


def test_release_gate_contains_full_required_sequence() -> None:
    root = Path(__file__).resolve().parents[1]
    script = (root / "verify-release.ps1").read_text(encoding="utf-8")
    for required in ("verify_release_environment.py", "verify_documentation.py", "ruff check",
                     "-m mypy", "-m pytest",
                     "audit_dependencies.py", "dependency-report.json", "diff --check",
                     "measure_capacity.py", "capacity-report.json",
                     "verify_foundation_ui.py", "build.ps1", "package-smoke", "release-report.json"):
        assert required in script
    for portable in ("portable-smoke-", "中文 空格", "check-config", "preparedConfig"):
        assert portable in script
    build = (root / "build.ps1").read_text(encoding="utf-8")
    assert "PyInstaller $requiredPyInstaller" in build
    assert "pip install" not in build
