import json
from pathlib import Path

from scripts.verify_documentation import broken_links, schema_tables, verify


def test_current_documentation_contracts() -> None:
    root = Path(__file__).resolve().parents[1]
    result = verify(root)
    assert result["documents"] > 20
    assert result["links"] > 50
    assert result["schema_tables"] == 5


def test_link_checker_rejects_missing_absolute_and_out_of_range_targets(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "AGENTS.md").write_text("", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "[missing](docs/no.md) [absolute](D:/private/file.md) [line](README.md#L99)\n",
        encoding="utf-8",
    )
    errors = broken_links(tmp_path)
    assert any("missing link" in value for value in errors)
    assert any("absolute link" in value for value in errors)
    assert any("line anchor outside" in value for value in errors)


def test_schema_table_parser_tracks_formal_tables(tmp_path: Path) -> None:
    (tmp_path / "sql").mkdir()
    (tmp_path / "sql/schema.sql").write_text(
        "CREATE TABLE IF NOT EXISTS one (id INT);\nCREATE TABLE IF NOT EXISTS two (id INT);\n",
        encoding="utf-8",
    )
    assert schema_tables(tmp_path) == {"one", "two"}


def test_stable_evidence_contains_no_secret_material() -> None:
    root = Path(__file__).resolve().parents[1]
    evidence = json.loads(
        (root / "docs/evidence/release-baseline-2026-09-27.json").read_text(encoding="utf-8")
    )
    serialized = json.dumps(evidence).lower()
    assert "password" not in serialized
    assert "mysql://" not in serialized and "redis://" not in serialized
