import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.plugins.datasets.astock import DatasetPlugin
from empire.plugins.pipeline.fingerprints import FingerprintCache


@pytest.mark.parametrize("namespace,version", [
    ("stocks", ["not-a-timestamp"]),
    ("stocks", ["2026-09-26T08:00:00.000000", "not-a-snapshot"]),
    ("stocks", ["2026-09-26T08:00:00.000000+00:00", "a" * 32]),
    ("news", ["not-a-timestamp"]),
    ("news", ["2026-09-26T00:00:00.000000+00:00"]),
    ("news", ["2026-09-26T00:00:00.000000+00:00", ""]),
    ("news", ["2026-09-26T00:00:00+00:00", "2026-09-26T00:00:00.000000+00:00"]),
    ("news", ["2026-09-26T00:00:00.000000+08:00", "2026-09-26T00:00:00.000000+00:00"]),
    ("news", ["9999-12-31T00:00:00.000000+00:00", "2026-09-26T00:00:00.000000+00:00"]),
    ("calendar", ["not-a-timestamp"]),
    ("calendar", ["2026-02-30T00:00:00.000000+00:00"]),
    ("calendar", ["2026-09-26T00:00:00.000000"]),
    ("calendar", ["2026-09-26T00:00:00.000000Z"]),
    ("calendar", ["2026-09-26T00:00:00.000000+00:00", "extra"]),
    ("calendar", [(datetime.now(UTC) + timedelta(days=1)).isoformat(timespec="microseconds")]),
])
async def test_malformed_dataset_versions_are_not_archive_evidence(namespace, version):
    store = SimpleNamespace(prefix="test", client=SimpleNamespace(eval=AsyncMock(return_value=[
        json.dumps({"hash": "a" * 64, "version": version})])))
    cache = FingerprintCache(store, {}, DatasetPlugin().fingerprint_version)
    assert await cache.get(namespace, "test-source", ["key"]) == {}


def test_version_contract_compares_parsed_times_and_limits_only_cache_trust():
    contract = DatasetPlugin().fingerprint_version("news")
    observed = datetime.now(UTC)
    text = observed.isoformat(timespec="microseconds")
    valid = [(observed + timedelta(minutes=4)).isoformat(timespec="microseconds"), text]
    assert contract.key(valid, now=observed)
    future = ["9999-12-31T00:00:00.000000+00:00", text]
    with pytest.raises(ValueError, match="来源版本"):
        contract.key(future, now=observed)
    assert contract.compare(future, valid) > 0


@pytest.mark.parametrize("namespace,version", [
    ("stocks", ["2000-01-01T08:00:00.000000", "a" * 32]),
    ("news", ["2000-01-01T00:00:00.000000+00:00", "2000-01-01T01:00:00.000000+00:00"]),
    ("calendar", ["2000-01-01T00:00:00.000000+00:00"]),
])
async def test_canonical_versions_remain_valid_proofs(namespace, version):
    value = {"hash": "a" * 64, "version": version}
    store = SimpleNamespace(prefix="test", client=SimpleNamespace(eval=AsyncMock(return_value=[json.dumps(value)])))
    cache = FingerprintCache(store, {}, DatasetPlugin().fingerprint_version)
    assert await cache.get(namespace, "test-source", ["key"]) == {"key": value}


async def test_deeply_nested_cache_json_is_a_miss_not_an_archive_failure():
    raw = '[' * 100000 + '0' + ']' * 100000
    store = SimpleNamespace(prefix="test", client=SimpleNamespace(eval=AsyncMock(return_value=[raw])))
    cache = FingerprintCache(store, {}, DatasetPlugin().fingerprint_version)
    assert await cache.get("stocks", "test-source", ["current"]) == {}
