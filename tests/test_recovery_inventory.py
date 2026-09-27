import json
from inspect import getsource
from pathlib import Path

import pytest

from scripts.mysql_recovery_inventory import (
    TABLES,
    collect_inventory,
    compare_inventory,
    file_identity,
)


def inventory(database="empire", *, changed=None):
    tables = {name: {"schema": {"primary_key": list(order)},
                     "content": {"rows": 1, "sha256": f"hash-{name}"}}
              for name, order in TABLES.items()}
    if changed:
        tables[changed]["content"]["rows"] = 2
    return {"schema_version": 1, "database": database, "tables": tables}


def test_backup_identity_streams_size_and_hash_without_exposing_path(tmp_path):
    backup = tmp_path / "empire-backup.sql"
    backup.write_bytes(b"safe fixture")
    identity = file_identity(backup)
    assert identity == {"name": "empire-backup.sql", "size_bytes": 12,
                        "sha256": "8722bd6c7fdcfcdccaaeac3c64d9c7684a09d6597464efa002a5fcaa992359c1"}
    assert str(tmp_path) not in json.dumps(identity)


def test_restore_comparison_requires_separate_explicit_drill_database():
    baseline = inventory()
    with pytest.raises(ValueError, match="_restore_drill"):
        compare_inventory(baseline, inventory("empire_copy"))
    with pytest.raises(ValueError, match="source database"):
        compare_inventory(inventory("empire_restore_drill"), inventory("empire_restore_drill"))


def test_restore_comparison_checks_all_business_state_and_settings_tables():
    baseline = inventory()
    result = compare_inventory(baseline, inventory("empire_restore_drill"))
    assert result["passed"] and result["tables_checked"] == list(TABLES)
    changed = compare_inventory(baseline, inventory("empire_restore_drill",
                                                    changed="finance_news"))
    assert not changed["passed"]
    assert [difference["table"] for difference in changed["differences"]] == ["finance_news"]


def test_inventory_implementation_and_runbook_preserve_recovery_safety_boundary():
    source = getsource(collect_inventory).upper()
    assert "START TRANSACTION" in source and "READ ONLY" in source
    assert not any(statement in source for statement in (
        "INSERT ", "UPDATE ", "DELETE ", "DROP ", "CREATE ", "ALTER ", "TRUNCATE "))
    root = Path(__file__).resolve().parents[1]
    runbook = (root / "docs/recovery-runbook.md").read_text(encoding="utf-8")
    for required in ("当前无已登记备份", "_restore_drill", "不得从 `collection_state`",
                     "生产恢复会改变或替换业务数据", "passed=true"):
        assert required in runbook
