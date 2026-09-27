"""Runtime archive confirmation backed by Redis with a safe SQL fallback."""

import json
from datetime import datetime, timedelta

from empire.contracts.plugin import PluginManifest
from empire.core.time import mysql_time
from empire.plugins.datasets.stocks import FINGERPRINT_VERSION
from empire.plugins.infra.collection_state import CollectionState


def _stock_marker_version(value):
    started = datetime.fromisoformat(value["started_at"])
    if started.tzinfo is not None or started.isoformat() != value["started_at"]:
        raise ValueError("股票状态开始时间格式无效")
    return [started.isoformat(timespec="microseconds"), value["snapshot_id"]]


def _read_stock_marker(raw, status):
    """Untrusted Redis progress must never fabricate archive completion."""
    try:
        value = json.loads(raw) if raw else None
        if not isinstance(value, dict) or value.get("status") != status:
            return None
        count = value.get("row_count")
        if (type(count) is not int or not 0 <= count <= 100000
                or type(value.get("expected_count")) is not int or value["expected_count"] != count
                or not isinstance(value.get("error_text"), str)):
            return None
        finished = datetime.fromisoformat(value["finished_at"])
        if finished.utcoffset() != timedelta(0) or finished.isoformat() != value["finished_at"]:
            return None
        FINGERPRINT_VERSION.key([
            mysql_time(finished).isoformat(timespec="microseconds"), value["snapshot_id"]
        ])
        if status == "complete":
            version = _stock_marker_version(value)
            FINGERPRINT_VERSION.key(version)
            if not count or value["error_text"] or datetime.fromisoformat(version[0]) > mysql_time(finished):
                return None
        elif count or not value["error_text"] or value.get("started_at") is not None:
            return None
        return value
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return None


class ArchiveConfirmationPlugin:
    manifest = PluginManifest(
        "infra.archive_confirmation", "归档完成确认",
        requires=("mysql.store", "redis.store"), provides=("archive.confirmation",),
        description="供采集器确认 Redis 队列已由统一归档器提交；缓存异常时回源 MySQL",
    )

    def __init__(self):
        self.mysql = self.redis = None

    async def start(self, context):
        self.mysql = context.get("mysql.store")
        self.redis = context.get("redis.store")
        return {"archive.confirmation": self}

    async def stock_status(self, source, job_key, project_id, snapshot_id):
        confirmed = await self.redis.client.get(f"{self.redis.prefix}:stocks:committed:{source}")
        value = _read_stock_marker(confirmed, "complete")
        if value and value["snapshot_id"] == snapshot_id:
            return value
        if value is None:
            state = await self.mysql.control(
                CollectionState(self.mysql, self.redis.prefix).read, source, project_id)
            committed = state.get("progress", {})
            if committed.get("snapshot_id") == snapshot_id:
                return committed
        result = await self.redis.client.get(f"{self.redis.prefix}:stocks:result:{source}")
        value = _read_stock_marker(result, "invalid")
        return value if value and value["snapshot_id"] == snapshot_id else None

    async def page_status(self, source, job_key, project_id, batch_id, page):
        return await CollectionState(self.mysql, self.redis.prefix).page_status(
            self.redis, source, job_key, project_id, batch_id, page)

    async def stop(self):
        self.mysql = self.redis = None

    def health(self):
        return {"status": "ok" if self.mysql and self.redis else "stopped"}
