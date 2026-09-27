from pathlib import Path

import pytest

from empire.core.config import load_config


def write_config(path: Path, *, ingest: str = "", archive: str = "") -> Path:
    path.write_text(
        "[redis]\nnamespace = 'empire:test'\n"
        f"[archive]\n{archive}\n"
        f"[ingest]\n{ingest}\n",
        encoding="utf-8",
    )
    return path


def test_default_ingest_capacity_is_covered_by_default_archive_index(tmp_path):
    config = load_config(write_config(tmp_path / "default.toml"))
    assert config["ingest"].get("max_queue_entries", 100000) == 100000
    assert config["archive"].get("index_max_entries", 100000) == 100000


@pytest.mark.parametrize("value", ["true", "'100'", "0", "1000001"])
def test_queue_capacity_rejects_invalid_values(tmp_path, value):
    path = write_config(tmp_path / "invalid.toml", ingest=f"max_queue_entries = {value}")
    with pytest.raises(ValueError, match="max_queue_entries"):
        load_config(path)


@pytest.mark.parametrize("value", ["true", "'1024'", "1023", "16777217"])
def test_page_budget_rejects_invalid_values(tmp_path, value):
    path = write_config(tmp_path / "invalid.toml", ingest=f"max_page_bytes = {value}")
    with pytest.raises(ValueError, match="max_page_bytes"):
        load_config(path)


@pytest.mark.parametrize(
    "ingest",
    [
        "low_watermark = true\nhigh_watermark = 0.7",
        "low_watermark = '0.5'\nhigh_watermark = 0.7",
        "low_watermark = 0.7\nhigh_watermark = 0.7",
        "low_watermark = 0.8\nhigh_watermark = 0.7",
        "low_watermark = 0.5\nhigh_watermark = 1.0",
    ],
)
def test_ingest_watermarks_require_ordered_fractions(tmp_path, ingest):
    path = write_config(tmp_path / "invalid.toml", ingest=ingest)
    with pytest.raises(ValueError, match="watermarks"):
        load_config(path)


def test_archive_index_must_cover_queue_capacity(tmp_path):
    path = write_config(
        tmp_path / "invalid.toml",
        ingest="max_queue_entries = 101",
        archive="index_max_entries = 100",
    )
    with pytest.raises(ValueError, match="index_max_entries"):
        load_config(path)
