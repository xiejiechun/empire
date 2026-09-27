from __future__ import annotations

import os
import re
import shutil
import sys
import tomllib
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        raise RuntimeError("Source project root is unavailable in a packaged application")
    return Path(__file__).resolve().parents[3]


def resource_root() -> Path:
    """Return immutable application resources, independent of the launch directory."""
    if getattr(sys, "frozen", False):
        bundled = getattr(sys, "_MEIPASS", None)
        if not bundled:
            raise RuntimeError("Packaged resource directory is unavailable")
        return Path(bundled).resolve()
    return project_root()


def user_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share"))
    path = base / "Empire"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_config_path() -> Path:
    return user_data_dir() / "config.toml"


class ConfigurationRequiredError(ValueError):
    """Raised after preparing the only default user configuration path."""


def _prepare_config(target: Path) -> None:
    template = resource_root() / "config" / "app.example.toml"
    if not template.is_file():
        raise RuntimeError(f"Application configuration template is missing: {template}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("xb") as destination, template.open("rb") as source:
            shutil.copyfileobj(source, destination)
    except FileExistsError:
        return


def load_config(path: str | Path | None = None) -> dict:
    target = Path(path).expanduser() if path else default_config_path()
    if not target.is_file():
        if path:
            raise ValueError(f"Configuration file does not exist: {target}")
        _prepare_config(target)
        raise ConfigurationRequiredError(
            f"首次运行配置已创建：{target.resolve()}。请填写 Redis/MySQL 连接信息后重新打开 Empire。"
        )
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
    cfg.setdefault("http", {})
    download_directory = cfg["http"].get("download_directory")
    if download_directory:
        download_path = Path(download_directory).expanduser()
        if not download_path.is_absolute():
            download_path = target.resolve().parent / download_path
        cfg["http"]["download_directory"] = str(download_path.resolve())
    namespace = cfg["redis"].get("namespace", "empire:dev")
    if not re.fullmatch(r"empire:[a-zA-Z0-9:_-]+", namespace):
        raise ValueError("Redis namespace must start with empire: and use simple identifiers")
    low = cfg["ingest"].get("low_watermark", .5)
    high = cfg["ingest"].get("high_watermark", .7)
    if (isinstance(low, bool) or isinstance(high, bool)
            or not isinstance(low, (int, float)) or not isinstance(high, (int, float))
            or not 0 < low < high < 1):
        raise ValueError("Ingestion watermarks must satisfy 0 < low < high < 1")
    queue_entries = cfg["ingest"].get("max_queue_entries", 100000)
    page_bytes = cfg["ingest"].get("max_page_bytes", 524288)
    index_entries = cfg["archive"].get("index_max_entries", 100000)
    if type(queue_entries) is not int or not 1 <= queue_entries <= 1000000:
        raise ValueError("ingest.max_queue_entries must be an integer from 1 to 1000000")
    if type(page_bytes) is not int or not 1024 <= page_bytes <= 16 * 1024 * 1024:
        raise ValueError("ingest.max_page_bytes must be an integer from 1 KiB to 16 MiB")
    if type(index_entries) is not int or index_entries < queue_entries:
        raise ValueError("archive.index_max_entries must cover ingest.max_queue_entries")
    if cfg["archive"].get("interval_seconds", 60) <= 0:
        raise ValueError("Archive interval must be positive")
    cfg["_path"] = str(target.resolve())
    return cfg
