import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.core.time import mysql_time
from empire.plugins.infra.archive_confirmation import ArchiveConfirmationPlugin


def marker():
    return {"snapshot_id": "a" * 32, "status": "complete", "row_count": 2,
            "expected_count": 2, "error_text": "",
            "started_at": mysql_time(datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
            "finished_at": datetime.now(UTC).isoformat()}


def damage(value, kind):
    if kind == "json":
        return "{"
    if kind == "deep-json":
        return '[' * 2000 + '0' + ']' * 2000
    if kind == "array":
        return "[]"
    value = copy.deepcopy(value)
    if kind == "status":
        value["status"] = "awaiting_archive"
    elif kind == "snapshot":
        value["snapshot_id"] = "not-a-snapshot"
    elif kind == "time":
        value["started_at"] = "invalid-time"
    elif kind == "timezone":
        value["started_at"] += "+00:00"
    elif kind == "future":
        value["started_at"] = "9999-01-01T00:00:00"
    elif kind == "count":
        value["expected_count"] = 3
    elif kind == "boolean":
        value["row_count"] = True
    elif kind == "unfinished":
        value["finished_at"] = None
    elif kind == "finish-before-start":
        value["finished_at"] = "2000-01-01T00:00:00+00:00"
    return json.dumps(value)


DAMAGE = ["json", "deep-json", "array", "status", "snapshot", "time", "timezone",
          "future", "count", "boolean", "unfinished", "finish-before-start"]


@pytest.mark.parametrize("kind", DAMAGE)
async def test_invalid_committed_marker_falls_back_to_sql_confirmation(kind):
    plugin = ArchiveConfirmationPlugin()
    value = marker()
    raw = damage(value, kind)
    plugin.redis = SimpleNamespace(prefix="test", client=SimpleNamespace(get=AsyncMock(return_value=raw)))
    plugin.mysql = SimpleNamespace(control=AsyncMock(return_value={"progress": value}))
    assert await plugin.stock_status(
        "sina", "sina-universe-v1", "sina-stocks", value["snapshot_id"]) == value
    assert plugin.mysql.control.await_count == 1


async def test_valid_markers_keep_fast_status_and_invalid_result_is_safe():
    plugin = ArchiveConfirmationPlugin()
    value = marker()
    plugin.redis = SimpleNamespace(prefix="test", client=SimpleNamespace(get=AsyncMock(return_value=json.dumps(value))))
    plugin.mysql = SimpleNamespace(read=AsyncMock(side_effect=AssertionError("valid cache status must not read SQL")))
    assert await plugin.stock_status(
        "sina", "sina-universe-v1", "sina-stocks", value["snapshot_id"]) == value
    for bad in ("{", "[]", '[' * 2000 + '0' + ']' * 2000):
        plugin.redis.client.get = AsyncMock(side_effect=[json.dumps(value), bad])
        assert await plugin.stock_status(
            "sina", "sina-universe-v1", "sina-stocks", "b" * 32) is None


async def test_missing_marker_uses_sql_progress_then_valid_invalid_result():
    plugin = ArchiveConfirmationPlugin()
    value = {**marker(), "status": "invalid", "row_count": 0, "expected_count": 0,
             "started_at": None, "error_text": "已确认分页缺失"}
    plugin.redis = SimpleNamespace(prefix="test", client=SimpleNamespace(get=AsyncMock(
        side_effect=[None, json.dumps(value)])))
    plugin.mysql = SimpleNamespace(control=AsyncMock(return_value={"progress": {}}))
    assert await plugin.stock_status(
        "sina", "sina-universe-v1", "sina-stocks", value["snapshot_id"]) == value


async def test_whole_second_marker_uses_the_current_auto_precision_contract():
    plugin = ArchiveConfirmationPlugin()
    value = marker()
    value["started_at"] = datetime.fromisoformat(value["started_at"]).replace(microsecond=0).isoformat()
    plugin.redis = SimpleNamespace(prefix="test", client=SimpleNamespace(get=AsyncMock(return_value=json.dumps(value))))
    plugin.mysql = SimpleNamespace(read=AsyncMock(side_effect=AssertionError("valid marker should be usable")))
    assert await plugin.stock_status(
        "sina", "sina-universe-v1", "sina-stocks", value["snapshot_id"]) == value
