"""Business-owned stocks.publication."""
import json
from datetime import datetime, timedelta

from empire.contracts.archive_version import ArchiveVersion
from empire.core.time import mysql_time

FINGERPRINT_NAMESPACE = "stocks"


FINGERPRINT_SOURCE = 'current'


FINGERPRINT_VERSION = ArchiveVersion(("china", "snapshot"), observed_index=0)


def _snapshot_marker_version(value):
    started = datetime.fromisoformat(value["started_at"])
    if started.tzinfo is not None or started.isoformat() != value["started_at"]:
        raise ValueError("股票状态开始时间格式无效")
    return [started.isoformat(timespec="microseconds"), value["snapshot_id"]]


def read_snapshot_marker(raw, status):
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
            version = _snapshot_marker_version(value)
            FINGERPRINT_VERSION.key(version)
            if not count or value["error_text"] or datetime.fromisoformat(version[0]) > mysql_time(finished):
                return None
        elif count or not value["error_text"] or value.get("started_at") is not None:
            return None
        return value
    except (ValueError, TypeError, KeyError, OverflowError, RecursionError):
        return None
