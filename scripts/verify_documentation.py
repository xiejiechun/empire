"""Verify local documentation links, operational contracts, and stable evidence."""
from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from urllib.parse import unquote

EXPECTED_TABLES = {"stock", "finance_news", "trade_calendar", "collection_state", "app_setting"}
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


def documentation_files(root: Path) -> list[Path]:
    values = [root / "README.md", root / "AGENTS.md"]
    for folder in ("docs", "deploy", "sql/changes"):
        values.extend((root / folder).rglob("*.md"))
    values.extend((root / "src").rglob("*.md"))
    return sorted(set(values))


def _link_target(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("<") and ">" in raw:
        return raw[1:raw.index(">")]
    return raw.split(maxsplit=1)[0]


def broken_links(root: Path) -> list[str]:
    errors: list[str] = []
    for document in documentation_files(root):
        text = document.read_text(encoding="utf-8")
        for number, line in enumerate(text.splitlines(), 1):
            for matched in LINK_RE.finditer(line):
                target = unquote(_link_target(matched.group(1)))
                if target.startswith(("http://", "https://", "mailto:", "codex://", "#")):
                    continue
                if re.match(r"^[A-Za-z]:[/\\]", target) or target.startswith(("/", "\\\\")):
                    errors.append(f"{document.relative_to(root)}:{number}: absolute link {target}")
                    continue
                path_text, _, fragment = target.partition("#")
                resolved = (document.parent / path_text).resolve()
                try:
                    resolved.relative_to(root.resolve())
                except ValueError:
                    errors.append(f"{document.relative_to(root)}:{number}: link escapes repository {target}")
                    continue
                if not resolved.exists():
                    errors.append(f"{document.relative_to(root)}:{number}: missing link {target}")
                    continue
                line_match = re.fullmatch(r"L(\d+)", fragment)
                if line_match and resolved.is_file():
                    line_count = len(resolved.read_text(encoding="utf-8", errors="replace").splitlines())
                    if int(line_match.group(1)) > line_count:
                        errors.append(f"{document.relative_to(root)}:{number}: line anchor outside file {target}")
    return errors


def schema_tables(root: Path) -> set[str]:
    schema = (root / "sql/schema.sql").read_text(encoding="utf-8")
    return set(re.findall(r"^CREATE TABLE IF NOT EXISTS\s+(\w+)", schema, re.MULTILINE))


def _assert_evidence(root: Path) -> None:
    path = root / "docs/evidence/release-baseline-2026-09-27.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    if set(value) != {"schema_version", "recorded_at_utc", "source", "gate", "artifacts",
                      "portable_distribution", "scope_limitations"}:
        raise RuntimeError("Release baseline evidence has an unexpected schema")
    if value["schema_version"] != 1 or not re.fullmatch(r"[0-9a-f]{40}", value["source"]["commit"]):
        raise RuntimeError("Release baseline source identity is invalid")
    for key in ("requirements_sha256", "dependency_report_sha256", "executable_sha256"):
        if not HASH_RE.fullmatch(value["artifacts"][key]):
            raise RuntimeError(f"Release baseline {key} is invalid")
    if value["gate"]["tests_passed"] <= 0 or value["gate"]["tests_skipped"] < 0:
        raise RuntimeError("Release baseline test counts are invalid")
    if not all(value["portable_distribution"].values()):
        raise RuntimeError("Release baseline portable distribution evidence is incomplete")
    serialized = json.dumps(value, ensure_ascii=False).lower()
    for forbidden in ("password", "redis://", "mysql://", "d:\\\\project", "c:\\\\users"):
        if forbidden in serialized:
            raise RuntimeError(f"Release baseline contains forbidden machine or credential data: {forbidden}")


def verify(root: Path) -> dict[str, int]:
    links = broken_links(root)
    if links:
        raise RuntimeError("Documentation links are invalid:\n" + "\n".join(links))
    tables = schema_tables(root)
    if tables != EXPECTED_TABLES:
        raise RuntimeError(f"Schema table contract changed: {sorted(tables)}")
    services = (root / "deploy/windows-services.md").read_text(encoding="utf-8")
    for table in sorted(tables):
        if f"`{table}`" not in services:
            raise RuntimeError(f"Windows service guide omits SQL table: {table}")
    if "网站覆盖设置会丢失" in services or "不会随 Redis 重启丢失" not in services:
        raise RuntimeError("Windows service guide contradicts MySQL configuration persistence")
    example = tomllib.loads((root / "config/app.example.toml").read_text(encoding="utf-8"))
    ingest = example["ingest"]
    required_capacity = (
        f"{ingest['max_queue_entries']:,}", f"{int(ingest['high_watermark'] * 100)}%",
        f"{int(ingest['low_watermark'] * 100)}%", f"{ingest['max_page_bytes'] // 1024} KiB",
    )
    if any(item not in services for item in required_capacity):
        raise RuntimeError("Windows service capacity text differs from app.example.toml")
    for document in documentation_files(root):
        for number, line in enumerate(document.read_text(encoding="utf-8").splitlines(), 1):
            if "config/local.toml" in line and not any(mark in line for mark in ("旧", "当时")):
                raise RuntimeError(
                    f"{document.relative_to(root)}:{number}: legacy config path is presented as current"
                )
    _assert_evidence(root)
    return {"documents": len(documentation_files(root)), "links": sum(
        len(LINK_RE.findall(path.read_text(encoding="utf-8")))
        for path in documentation_files(root)
    ), "schema_tables": len(tables)}


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[1]
    result = verify(project_root)
    print("PASS documentation contracts: " + ", ".join(
        f"{key}={value}" for key, value in result.items()
    ))
