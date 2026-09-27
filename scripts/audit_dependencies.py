"""Generate reproducible dependency inventory and optional PyPI security evidence."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import sys
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, metadata, version
from pathlib import Path
from typing import Any

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name, parse_wheel_filename

if __package__:
    from scripts.verify_release_environment import LockedRequirement, locked_requirements
else:
    from verify_release_environment import LockedRequirement, locked_requirements

GROUPS = {
    "qt": {"pyside6", "pyside6-addons", "pyside6-essentials", "shiboken6"},
    "validation": {"pydantic", "pydantic-core", "annotated-types", "typing-inspection"},
    "database": {"sqlalchemy", "greenlet", "pymysql", "cryptography", "cffi", "pycparser"},
    "network": {"httpx", "httpcore", "h11", "anyio", "socksio", "certifi", "idna"},
    "redis": {"redis"},
    "build": {"pyinstaller", "pyinstaller-hooks-contrib", "altgraph", "pefile",
              "pywin32-ctypes", "setuptools"},
    "test-quality": {"pytest", "pytest-asyncio", "ruff", "mypy", "mypy-extensions",
                     "iniconfig", "pluggy", "pygments", "pathspec", "librt", "colorama"},
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def compatibility_group(name: str) -> str:
    canonical = canonicalize_name(name)
    for group, members in GROUPS.items():
        if canonical in members:
            return group
    return "runtime-support"


def _declared_names(project: dict[str, Any], field: str) -> set[str]:
    values = project["project"].get(field, [])
    if isinstance(values, dict):
        values = [item for group in values.values() for item in group]
    return {canonicalize_name(Requirement(item).name) for item in values}


def _wheel_evidence(directory: Path, locked: LockedRequirement) -> dict[str, str] | None:
    target = canonicalize_name(locked.requirement.name)
    wanted_version = next(iter(locked.requirement.specifier)).version
    matches: list[dict[str, str]] = []
    for path in directory.glob("*.whl"):
        name, wheel_version, _build, _tags = parse_wheel_filename(path.name)
        if canonicalize_name(name) == target and str(wheel_version) == wanted_version:
            digest = sha256(path)
            if digest not in locked.hashes:
                raise RuntimeError(f"Wheel hash is not authorized by requirements.lock: {path.name}")
            matches.append({"filename": path.name, "sha256": digest})
    if len(matches) != 1:
        raise RuntimeError(f"Expected one locked wheel for {locked.requirement}, found {len(matches)}")
    return matches[0]


def build_inventory(root: Path, wheel_directory: Path | None = None) -> dict[str, Any]:
    lock_path = root / "requirements.lock"
    entries = locked_requirements(lock_path)
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = _declared_names(project, "dependencies")
    development = _declared_names(project, "optional-dependencies")
    components = []
    for locked in entries:
        requirement = locked.requirement
        canonical = canonicalize_name(requirement.name)
        try:
            installed = version(requirement.name)
            package_meta = metadata(requirement.name)
        except PackageNotFoundError as exc:
            raise RuntimeError(f"Locked dependency is not installed: {requirement.name}") from exc
        if installed not in requirement.specifier:
            raise RuntimeError(
                f"Installed dependency differs from lock: {requirement.name} {installed}"
            )
        scope = "direct-runtime" if canonical in runtime else (
            "direct-development" if canonical in development else "transitive"
        )
        component: dict[str, Any] = {
            "name": canonical,
            "version": installed,
            "scope": scope,
            "compatibility_group": compatibility_group(canonical),
            "license": package_meta.get("License-Expression") or package_meta.get("License") or None,
            "locked_sha256": list(locked.hashes),
            "installed_matches": True,
        }
        if wheel_directory is not None:
            component["wheel"] = _wheel_evidence(wheel_directory, locked)
        components.append(component)
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "scope": "Python packages locked for Empire; excludes OS, driver and dynamically loaded native components",
        "target": {"system": "Windows", "machine": "AMD64", "python": "3.12"},
        "generator": {"python": platform.python_version(), "platform": platform.platform()},
        "requirements_sha256": sha256(lock_path),
        "component_count": len(components),
        "components": components,
    }


def _query_pypi_release(component: dict[str, Any]) -> dict[str, Any]:
    name, locked_version = component["name"], component["version"]
    url = f"https://pypi.org/pypi/{name}/{locked_version}/json"
    item: dict[str, Any] = {"name": name, "version": locked_version, "source": url}
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Empire dependency audit/1"})
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.load(response)
        item["status"] = "queried"
        item["vulnerabilities"] = payload.get("vulnerabilities", [])
    except (OSError, ValueError, urllib.error.URLError) as exc:
        item.update(status="query_failed", error=f"{type(exc).__name__}: {exc}")
    return item


def query_pypi(inventory: dict[str, Any]) -> dict[str, Any]:
    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="pypi-audit") as pool:
        results = list(pool.map(_query_pypi_release, inventory["components"]))
    complete = all(item["status"] == "queried" for item in results)
    return {
        "schema_version": 1,
        "queried_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "source": "PyPI JSON release metadata",
        "complete": complete,
        "limitation": "Empty PyPI metadata is not proof that a package or native component has no vulnerability.",
        "requirements_sha256": inventory["requirements_sha256"],
        "results": results,
    }


def write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--wheel-directory", type=Path)
    parser.add_argument("--online-output", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    inventory = build_inventory(root, args.wheel_directory)
    write_json(args.output, inventory)
    if args.online_output is not None:
        security = query_pypi(inventory)
        write_json(args.online_output, security)
        if not security["complete"]:
            print("WARN online dependency evidence is incomplete", file=sys.stderr)
    print(f"PASS dependency inventory: {inventory['component_count']} locked components")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
