"""Seven retired products cannot reappear or affect shared theme ownership."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from empire.bootstrap import build_manager
from empire.contracts.dataset import DatasetContribution
from empire.features.yuanhang import dataset
from empire.plugins.datasets.astock import DatasetPlugin
from scripts.retire_kaipanla_market import DATASETS, PROJECTS, TABLES, exclusive_keys


def test_only_theme_tasks_remain_and_no_retired_writer_or_page_is_registered():
    manager = build_manager(dict(redis={}, mysql={}, archive={}, ingest={}, rate_groups={}))
    tasks = manager.entries["collection.control"].plugin.definitions
    assert len(tasks) == 52
    assert {t for t in tasks if t.startswith("kaipanla-")} == {
        "kaipanla-themes",
        "kaipanla-theme-details",
    }
    catalog = manager.entries["dataset.astock"].plugin
    assert set(DATASETS).isdisjoint(catalog.datasets)
    assert not any(".kaipanla_" in key for key in manager.entries)
    from empire.desktop_bridge.preview_catalog import views

    for project in PROJECTS:
        assert not views(project)


def test_explicit_cleanup_cannot_target_theme_or_shared_platform_keys():
    keys = exclusive_keys("test:retire")
    assert len(keys) == len(set(keys)) == 56
    assert not any("theme" in k or ":rate:" in k or ":identity" in k for k in keys)
    assert len(TABLES) == 9 and all(t.startswith("stock_") for t in TABLES)
    assert "stock" not in TABLES


def test_yuanhang_financial_bucket_is_separate_without_changing_version_contract():
    catalog = DatasetPlugin([DatasetContribution(dataset, "incremental", {})])
    price = SimpleNamespace(dataset=dataset.PRICE_DATASET, schema_version=1, source="ths_yuanhang")
    financial = SimpleNamespace(
        dataset=dataset.FINANCIAL_DATASET, schema_version=1, source="ths_yuanhang"
    )
    assert catalog.fingerprint_source(price) == "ths_yuanhang"
    assert catalog.fingerprint_source(financial) == "ths_yuanhang:financial"
    assert catalog.namespace(price) == catalog.namespace(financial)
    assert catalog.fingerprint_version(catalog.namespace(price)) is dataset.FINGERPRINT_VERSION


def test_exact_retirement_cannot_hide_other_removals():
    import copy
    import json

    from scripts.assembly_retirements import semantic_baseline

    root = Path(__file__).resolve().parents[1]
    baseline = json.loads(
        (root / "docs/evidence/assembly-baseline-2026-10-19.json").read_text("utf8")
    )
    changes = json.loads((root / "docs/assembly-feature-changes.json").read_text("utf8"))
    retirement = next(c for c in changes if c["path"] == "retirement.kaipanla_market")
    current = copy.deepcopy(baseline)
    for domain in ("semantic", "bindings"):
        for group, entries in retirement["before"][domain].items():
            for key in entries:
                del current[domain][group][key]
    assert semantic_baseline(baseline, current, [retirement], root) == current
    current["semantic"]["tasks"]["kaipanla-quote"] = {}
    with pytest.raises(ValueError, match="Retirement differs"):
        semantic_baseline(baseline, current, [retirement], root)
