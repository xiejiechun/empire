import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from empire.plugins.collection.records import (
    APPEND,
    CLEAR,
    RecordsPlugin,
    project_id_for,
)


class MemoryRedis:
    """Model the two atomic Lua operations, including another task appending records."""

    def __init__(self):
        self.lists = {}
        self.lock = asyncio.Lock()

    async def eval(self, script, count, key, *args):
        assert count == 1
        async with self.lock:
            entries = self.lists.setdefault(key, [])
            if script == APPEND:
                raw, ident, limit = args
                entries[:] = [item for item in entries if json.loads(item)["id"] != ident]
                entries.insert(0, raw)
                del entries[int(limit):]
                return 1
            assert script == CLEAR
            before = len(entries)
            entries[:] = [item for item in entries if json.loads(item)["id"] not in args]
            return before - len(entries)

    async def lrange(self, key, start, end):
        return list(self.lists.get(key, [])[start:end + 1])


@pytest.fixture
def records():
    plugin = RecordsPlugin(secrets=("KnownDatabaseCredential",))
    plugin.redis = SimpleNamespace(prefix="isolated-test", client=MemoryRedis())
    return plugin


async def test_errors_keep_latest_300_independently_per_project_and_retry_deduplicates(records):
    for index in range(305):
        await records.add_error("sina-stocks", stage="parse", error="bad", record_id=f"sina-{index}")
    await records.add_error("another-project", stage="parse", error="bad", record_id="other")
    rows = await records.list_errors("sina-stocks")
    assert len(rows) == 300
    assert rows[0]["id"] == "sina-304" and rows[-1]["id"] == "sina-5"
    assert len(await records.list_errors("another-project")) == 1
    await records.add_error("sina-stocks", stage="parse", error="retry", record_id="sina-5")
    retried = await records.list_errors("sina-stocks")
    assert len(retried) == 300 and retried[0]["error"] == "retry"


async def test_archive_history_is_separate_bounded_and_never_keeps_response_bodies(records):
    for index in range(105):
        await records.add_archive("sina-stocks", {"id": str(index), "status": "complete",
                                                  "count": 10, "raw_body": "do not retain"})
    await records.add_archive("other", {"id": "other", "status": "error"})
    rows = await records.list_archives("sina-stocks")
    assert len(rows) == 100 and rows[0]["id"] == "104" and rows[-1]["id"] == "5"
    assert all("raw_body" not in item for item in rows)
    assert rows[0]["count"] == 10
    assert len(await records.list_archives("other")) == 1
    assert await records.list_errors("sina-stocks") == []


async def test_clear_only_reviewed_ids_preserves_later_and_unresolved_errors(records):
    await records.add_error("sina-stocks", stage="parse", error="fixed", record_id="reviewed")
    await records.add_error("sina-stocks", stage="parse", error="unresolved", record_id="unresolved")
    await records.add_error("other", stage="parse", error="other", record_id="reviewed")
    await asyncio.gather(
        records.add_error("sina-stocks", stage="parse", error="new", record_id="new-arrival"),
        records.clear_errors("sina-stocks", ["reviewed"]),
    )
    assert {row["id"] for row in await records.list_errors("sina-stocks")} == {"unresolved", "new-arrival"}
    assert len(await records.list_errors("other")) == 1
    assert await records.clear_errors("sina-stocks", ["reviewed"]) == 0
    assert await records.clear_errors("sina-stocks", []) == 0


async def test_diagnostics_bound_body_and_metadata_and_preserve_original_fingerprint(records):
    raw = ("错误响应" * 30000).encode()
    row = await records.add_error("sina-stocks", stage="json", error="e" * 20000, raw_body=raw,
                                  metadata={str(i): "x" * 10000 for i in range(1000)})
    assert len(row["body"].encode()) <= 65536
    assert row["body_truncated"] is True
    assert row["original_bytes"] == len(raw)
    assert row["original_sha256"] == hashlib.sha256(raw).hexdigest()
    assert len(row["error"].encode()) <= 4096
    assert len(json.dumps(row["metadata"], ensure_ascii=False).encode()) < 8500
    assert len(json.dumps(row, ensure_ascii=False).encode()) < 100000
    assert row["version"] and row["created_at"] and row["id"]


async def test_credentials_are_redacted_across_body_error_url_and_metadata(records):
    body = json.dumps({"password": "body-secret", "nested": {"api_key": "key-secret"},
                       "message": "KnownDatabaseCredential", "cookie": "session-cookie"})
    row = await records.add_error(
        "sina-stocks", stage="parse", error="failed password=error-secret KnownDatabaseCredential",
        request_url="https://username:userinfo-secret@example.com/list?token=query-secret&page=2#hidden",
        raw_body=body,
        metadata={"Authorization": "Bearer metadata-secret", "headers": {"Cookie": "header-secret"}},
    )
    serialized = json.dumps(row)
    for secret in ("body-secret", "key-secret", "session-cookie", "KnownDatabaseCredential",
                   "error-secret", "userinfo-secret", "query-secret", "metadata-secret", "header-secret"):
        assert secret not in serialized
    assert "page=2" in row["request_url"]
    assert "[REDACTED]" in serialized


async def test_error_body_keeps_all_nonsecret_rows_within_size_limit(records):
    raw = json.dumps([{"code": f"{i:06d}", "name": "测试"} for i in range(80)], ensure_ascii=False)
    row = await records.add_error("sina-stocks", stage="page", error="bad count", raw_body=raw)
    assert len(json.loads(row["body"])) == 80
    assert row["body_truncated"] is False


async def test_non_json_credential_headers_are_redacted(records):
    raw = "Authorization: Bearer abcdefgh\nCookie: session=anothersecret\npassword='thirdsecret'"
    row = await records.add_error("sina-stocks", stage="json", error="bad", raw_body=raw)
    assert all(secret not in row["body"] for secret in ("abcdefgh", "anothersecret", "thirdsecret"))


async def test_truncated_or_invalid_json_does_not_expose_quoted_auth_and_cookies(records):
    raw = '{"Authorization": "Bearer secret-auth", "Cookie": "secret-cookie", "broken": '
    row = await records.add_error("sina-stocks", stage="json", error="malformed JSON", raw_body=raw)
    assert "secret-auth" not in row["body"]
    assert "secret-cookie" not in row["body"]


def test_collection_project_mapping_is_stable_and_safe():
    assert project_id_for("sina", "") == "sina-stocks"
    assert project_id_for("sina", "future-sina-news") == "future-sina-news"
    assert project_id_for("", "sina-universe-v1") == "sina-stocks"
    assert project_id_for("future-source", "future-project") == "future-project"
    assert ":" not in project_id_for("future:source")


async def test_gbk_error_body_is_readable_and_fingerprint_uses_original_bytes(records):
    raw = '{"error":"请求过于频繁"}'.encode("gbk")
    row = await records.add_error("sina-stocks", stage="page", error="bad shape", raw_body=raw)
    assert "请求过于频繁" in row["body"]
    assert row["original_sha256"] == hashlib.sha256(raw).hexdigest()


def test_known_credentials_are_also_redacted_when_url_encoded():
    records = RecordsPlugin(secrets=("complex@+/password",))
    assert "complex" not in records.sanitize_text("mysql+pymysql://user:complex%40%2B%2Fpassword@localhost/db")
    assert "complex" not in records.sanitize_text("driver error complex%40%2B%2Fpassword")


async def test_invalid_project_key_and_unbounded_clear_input_are_rejected(records):
    with pytest.raises(ValueError):
        await records.list_errors("other:namespace")
    with pytest.raises(ValueError):
        await records.clear_errors("sina-stocks", [str(i) for i in range(301)])
