from __future__ import annotations

import logging
import os
import re
import tomllib
from pathlib import Path
from urllib.parse import quote


def project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def user_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    path = base / "Empire"
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config(path: str | Path | None = None) -> dict:
    target = Path(path) if path else project_root() / "config" / "local.toml"
    if not target.is_file():
        if path:
            raise ValueError(f"Configuration file does not exist: {target}")
        target = project_root() / "config" / "app.example.toml"
    with target.open("rb") as file:
        cfg = tomllib.load(file)
    for section in ("redis", "mysql"):
        cfg.setdefault(section, {})
        override = os.environ.get(f"EMPIRE_{section.upper()}_PASSWORD")
        if override is not None:
            cfg[section]["password"] = override
    cfg.setdefault("archive", {})
    cfg.setdefault("ingest", {})
    cfg.setdefault("sina_universe", {})
    cfg.setdefault("rate_groups", {})
    namespace = cfg["redis"].get("namespace", "empire:dev")
    if not re.fullmatch(r"empire:[a-zA-Z0-9:_-]+", namespace):
        raise ValueError("Redis namespace must start with empire: and use simple identifiers")
    if not 0 < cfg["ingest"].get("low_watermark", .5) < cfg["ingest"].get(
        "high_watermark", .7
    ) < 1:
        raise ValueError("Ingestion watermarks must satisfy 0 < low < high < 1")
    if cfg["archive"].get("interval_seconds", 60) <= 0:
        raise ValueError("Archive interval must be positive")
    cfg["_path"] = str(target.resolve())
    return cfg


def redact(message: object, cfg: dict) -> str:
    text = str(message)
    for section in ("redis", "mysql"):
        password = cfg.get(section, {}).get("password")
        if password:
            text = text.replace(password, "[REDACTED]").replace(quote(password, safe=""), "[REDACTED]")
    return re.sub(r"(redis(?:s)?://[^:\s]*:)[^@\s]+@", r"\1[REDACTED]@", text)


class RedactingFormatter(logging.Formatter):
    def __init__(self, cfg: dict) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self.cfg = cfg

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record), self.cfg)
