"""Historical measurements remain usable only for exactly unchanged old schemas."""

import hashlib
import json
from pathlib import Path

import pytest

from scripts.capacity_schema_additions import preserved_binding

ROOT = Path(__file__).resolve().parents[1]


def fixture(tmp_path):
    proof = json.loads((ROOT / "docs/capacity-schema-additions.json").read_text("utf8"))
    for name in [
        "docs/capacity-schema-additions.json",
        *proof["baselines"],
        *proof["baselines"].values(),
        proof["design"],
        *proof["tests"],
    ]:
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / name).read_bytes())
    return {
        key: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
        for key, name in proof["baselines"].items()
    }


def test_original_bytes_and_only_additive_tables(tmp_path):
    checksums = fixture(tmp_path)
    for path, checksum in checksums.items():
        assert preserved_binding(tmp_path, path, checksum)
    assert not preserved_binding(tmp_path, "src/unknown.py", "0" * 64)
    assert not preserved_binding(tmp_path, "sql/schema.sql", "0" * 64)


def test_proof_cannot_expand_resources_or_escape_workspace(tmp_path):
    checksums = fixture(tmp_path)
    path = tmp_path / "docs/capacity-schema-additions.json"
    proof = json.loads(path.read_text("utf8"))
    proof["baselines"]["scripts/other.py"] = "docs/evidence/other.py"
    path.write_text(json.dumps(proof), "utf8")
    assert not preserved_binding(tmp_path, "sql/schema.sql", checksums["sql/schema.sql"])
    proof["baselines"].pop("scripts/other.py")
    proof["baselines"]["sql/schema.sql"] = "../outside.sql"
    path.write_text(json.dumps(proof), "utf8")
    with pytest.raises(ValueError, match="越出项目"):
        preserved_binding(tmp_path, "sql/schema.sql", checksums["sql/schema.sql"])


@pytest.mark.parametrize("kind", ["ddl", "shape", "ownership", "extra"])
def test_existing_semantic_changes_or_unregistered_additions_fail(tmp_path, kind):
    checksums = fixture(tmp_path)
    if kind in ("ddl", "extra"):
        p = tmp_path / "sql/schema.sql"
        value = p.read_text("utf8")
        value = (
            value.replace(
                "CREATE TABLE IF NOT EXISTS stock (", "CREATE TABLE IF NOT EXISTS stock_changed ("
            )
            if kind == "ddl"
            else value + "\nCREATE TABLE IF NOT EXISTS unexpected (id INT);"
        )
        p.write_text(value, "utf8")
    else:
        p = tmp_path / (
            "sql/schema-contract.json" if kind == "shape" else "sql/business-schema.json"
        )
        value = json.loads(p.read_text("utf8"))
        if kind == "shape":
            value["tables"]["stock"]["primary"] = ["name"]
        else:
            value["fixed_sources"]["stock"] = "changed"
        p.write_text(json.dumps(value), "utf8")
    with pytest.raises(ValueError, match="改变|集合不同"):
        preserved_binding(tmp_path, "sql/schema.sql", checksums["sql/schema.sql"])
