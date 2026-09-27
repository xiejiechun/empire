"""Fail fast when the release interpreter or installed locked dependencies differ."""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from packaging.requirements import Requirement

from empire import __version__

_HASH_RE = re.compile(r"--hash=sha256:([0-9a-fA-F]{64})$")


@dataclass(frozen=True)
class LockedRequirement:
    requirement: Requirement
    hashes: tuple[str, ...]


def _logical_lines(path: Path) -> list[str]:
    values: list[str] = []
    pending = ""
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        continued = line.endswith("\\")
        part = line[:-1].rstrip() if continued else line
        pending = f"{pending} {part}".strip()
        if not continued:
            values.append(pending)
            pending = ""
    if pending:
        raise RuntimeError(f"Unterminated continuation in release lock: {path}")
    return values


def locked_requirements(path: Path) -> list[LockedRequirement]:
    values: list[LockedRequirement] = []
    seen: set[str] = set()
    for line in _logical_lines(path):
        parts = line.split()
        requirement = Requirement(parts[0])
        specifiers = list(requirement.specifier)
        if (len(specifiers) != 1 or specifiers[0].operator != "=="
                or specifiers[0].version.endswith(".*")):
            raise RuntimeError(f"Release lock must use one exact version: {line}")
        hashes: list[str] = []
        for value in parts[1:]:
            matched = _HASH_RE.fullmatch(value)
            if matched is None:
                raise RuntimeError(f"Unsupported release lock option: {value}")
            hashes.append(matched.group(1).lower())
        if not hashes:
            raise RuntimeError(f"Release lock entry requires a SHA-256 hash: {requirement}")
        canonical = requirement.name.lower().replace("_", "-")
        if canonical in seen:
            raise RuntimeError(f"Duplicate release lock package: {requirement.name}")
        seen.add(canonical)
        values.append(LockedRequirement(requirement, tuple(hashes)))
    return values


def verify(root: Path) -> None:
    if sys.version_info[:2] != (3, 12):
        raise RuntimeError(f"Release requires Python 3.12.x, found {sys.version.split()[0]}")
    project = (root / "pyproject.toml").read_text(encoding="utf-8")
    if f'version = "{__version__}"' not in project:
        raise RuntimeError("pyproject.toml and empire.__version__ differ")
    mismatches = []
    for locked in locked_requirements(root / "requirements.lock"):
        requirement = locked.requirement
        try:
            installed = version(requirement.name)
        except PackageNotFoundError:
            mismatches.append(f"{requirement.name}: missing")
            continue
        if installed not in requirement.specifier:
            mismatches.append(f"{requirement.name}: installed {installed}, expected {requirement.specifier}")
    if mismatches:
        raise RuntimeError("Release environment differs from requirements.lock:\n" + "\n".join(mismatches))
    if version("pyinstaller") != "6.22.3":
        raise RuntimeError("PyInstaller build version must remain synchronized with build.ps1")


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    verify(project_root)
    print(f"PASS Python {sys.version.split()[0]} · Empire {__version__} · locked environment")
