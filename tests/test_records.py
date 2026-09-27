import asyncio
import hashlib
import json
from types import SimpleNamespace

import pytest

from empire.core.identity import safe_project_id
from empire.plugins.collection.records import (
    APPEND,
    CLEAR,
    GET_ERROR,
    LIST_ERROR_SUMMARIES,
    RecordsPlugin,
)


class MemoryRedis:
    """Model the two atomic Lua operations, including another task appending records."""

    def __init__(self):
        self.lists = {}
        self.revisions = {}
        self.lock = asyncio.Lock()

    async def eval(self, script, count, key, *args):
        async with self.lock:
            entries = self.lists.setdefault(key, [])
            if script == APPEND:
                assert count == 2
                revision_key, raw, ident, limit = args
                entries[:] = [item for item in entries if json.loads(item)["id"] != ident]
                entries.insert(0, raw)
                del entries[int(limit):]
                self.revisions[revision_key] = self.revisions.get(revision_key, 0) + 1
                return 1
            if script == CLEAR:
                assert count == 2
                revision_key, *selected = args
                before = len(entries)
                entries[:] = [item for item in entries if json.loads(item)["id"] not in selected]
                if before != len(entries):
                    self.revisions[revision_key] = self.revisions.get(revision_key, 0) + 1
                return before - len(entries)
            if script == LIST_ERROR_SUMMARIES:
                assert count == 2
                revision_key, known, offset, limit = args
                revision = str(self.revisions.get(revision_key, 0))
                if known == revision:
                    return [revision, str(len(entries)), "0"]
                offset, limit = int(offset), int(limit)
                if entries and offset >= len(entries):
                    offset = (len(entries) - 1) // limit * limit
                result = [revision, str(len(entries)), "1", str(offset)]
                for raw in entries[offset:offset + limit]:
                    row = json.loads(raw)
                    result.append(json.dumps({name: row.get(name) for name in (
                        "id", "project_id", "created_at", "stage", "error", "status_code")}))
                return result
            assert script == GET_ERROR and count == 1
            return next((raw for raw in entries if json.loads(raw)["id"] == args[0]), None)

    async def lrange(self, key, start, end):
        return list(self.lists.get(key, [])[start:end + 1])


@pytest.fixture
def records():
    plugin = RecordsPlugin(secrets=("KnownDatabaseCredential",))
    plugin.redis = SimpleNamespace(prefix="isolated-test", client=MemoryRedis())
    return plugin


async def summaries(records, project):
    result = []
    for offset in range(0, 300, 100):
        page = await records.list_error_summaries(project, offset, 100)
        result.extend(page["rows"])
        if offset + 100 >= page["total"]:
            break
    return result


async def test_errors_keep_latest_300_independently_per_project_and_retry_deduplicates(records):
    for index in range(305):
        await records.add_error("sina-stocks", stage="parse", error="bad", record_id=f"sina-{index}")
    await records.add_error("another-project", stage="parse", error="bad", record_id="other")
    rows = await summaries(records, "sina-stocks")
    assert len(rows) == 300
    assert rows[0]["id"] == "sina-304" and rows[-1]["id"] == "sina-5"
    assert len(await summaries(records, "another-project")) == 1
    await records.add_error("sina-stocks", stage="parse", error="retry", record_id="sina-5")
    retried = await summaries(records, "sina-stocks")
    assert len(retried) == 300 and retried[0]["error"] == "retry"


async def test_error_list_is_summary_only_and_unchanged_revision_has_no_rows(records):
    await records.add_error("sina-stocks", stage="download", error="large",
                            raw_body=b"x" * 65536, record_id="large")
    first = await records.list_error_summaries("sina-stocks")
    assert first["total"] == 1 and first["changed"]
    assert set(first["rows"][0]) == {
        "id", "project_id", "created_at", "stage", "error", "status_code"}
    assert "body" not in json.dumps(first)
    unchanged = await records.list_error_summaries(
        "sina-stocks", known_revision=first["revision"])
    assert unchanged == {"revision": first["revision"], "total": 1, "changed": False,
                         "offset": 0, "limit": 50, "rows": []}
    detail = await records.get_error("sina-stocks", "large")
    assert len(detail["body"].encode()) == 65536
    assert await records.get_error("sina-stocks", "missing") is None
    await records.add_error("sina-stocks", stage="download", error="revised",
                            raw_body=b"y", record_id="large")
    revised = await records.list_error_summaries(
        "sina-stocks", known_revision=first["revision"])
    assert revised["changed"] and revised["revision"] != first["revision"]
    assert revised["rows"][0]["error"] == "revised"


async def test_error_summary_page_bounds_and_clamps_after_removal(records):
    for index in range(55):
        await records.add_error("sina-stocks", stage="parse", error="bad", record_id=str(index))
    second = await records.list_error_summaries("sina-stocks", 50, 50)
    assert second["offset"] == 50 and len(second["rows"]) == 5
    await records.clear_errors("sina-stocks", [str(index) for index in range(50)])
    clamped = await records.list_error_summaries("sina-stocks", 50, 50)
    assert clamped["offset"] == 0 and clamped["total"] == 5
    with pytest.raises(ValueError):
        await records.list_error_summaries("sina-stocks", 300, 50)
    with pytest.raises(ValueError):
        await records.get_error("sina-stocks", "")


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
    assert (await records.list_error_summaries("sina-stocks"))["rows"] == []


async def test_clear_only_reviewed_ids_preserves_later_and_unresolved_errors(records):
    await records.add_error("sina-stocks", stage="parse", error="fixed", record_id="reviewed")
    await records.add_error("sina-stocks", stage="parse", error="unresolved", record_id="unresolved")
    await records.add_error("other", stage="parse", error="other", record_id="reviewed")
    await asyncio.gather(
        records.add_error("sina-stocks", stage="parse", error="new", record_id="new-arrival"),
        records.clear_errors("sina-stocks", ["reviewed"]),
    )
    assert {row["id"] for row in (await records.list_error_summaries("sina-stocks"))["rows"]} == {"unresolved", "new-arrival"}
    assert len((await records.list_error_summaries("other"))["rows"]) == 1
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


def test_explicit_collection_project_identity_is_stable_and_safe():
    assert safe_project_id("sina-stocks") == "sina-stocks"
    assert safe_project_id("future-project") == "future-project"
    assert ":" not in safe_project_id("future:source")


async def test_gbk_error_body_is_readable_and_fingerprint_uses_original_bytes(records):
    raw = '{"error":"请求过于频繁"}'.encode("gbk")
    row = await records.add_error("sina-stocks", stage="page", error="bad shape", raw_body=raw)
    assert "请求过于频繁" in row["body"]
    assert row["original_sha256"] == hashlib.sha256(raw).hexdigest()


async def test_complete_body_with_retained_prefix_keeps_full_length_and_digest(records):
    original = b"x" * (100 * 1024)
    digest = hashlib.sha256(original).hexdigest()
    row = await records.add_error("sina-stocks", stage="page_validation", error="invalid page",
                                  raw_body=original[:65536], observed_bytes=len(original),
                                  body_sha256=digest)
    assert row["body_complete"] and row["body_truncated"]
    assert row["original_bytes"] == len(original) and row["original_sha256"] == digest


def test_known_credentials_are_also_redacted_when_url_encoded():
    records = RecordsPlugin(secrets=("complex@+/password",))
    assert "complex" not in records.sanitize_text("mysql+pymysql://user:complex%40%2B%2Fpassword@localhost/db")
    assert "complex" not in records.sanitize_text("driver error complex%40%2B%2Fpassword")


async def test_invalid_project_key_and_unbounded_clear_input_are_rejected(records):
    with pytest.raises(ValueError):
        await records.list_error_summaries("other:namespace")
    with pytest.raises(ValueError):
        await records.clear_errors("sina-stocks", [str(i) for i in range(301)])


@pytest.mark.parametrize("password", ['"', "\\", 'special"slash\\@+中文'])
async def test_structured_body_with_special_password_preserves_json_and_keys(records, password):
    from empire.core.redaction import Redactor

    records.redactor = Redactor((password,))
    source = {"password": password, 'quoted"field': ["failure " + password, "safe"]}
    row = await records.add_error("sina-stocks", stage="parse", error="bad", raw_body=json.dumps(source))
    body = json.loads(row["body"])
    assert set(body) == set(source)
    assert body["password"] == "[REDACTED]"
    assert body['quoted"field'] == ["failure [REDACTED]", "safe"]


async def test_partial_download_records_do_not_claim_complete_length_or_digest(records):
    row = await records.add_error("sina-stocks", stage="download", error="too large",
                                  raw_body=b"retained prefix", raw_body_complete=False,
                                  observed_bytes=2 * 1024 * 1024)
    assert row["original_bytes"] is None and row["original_sha256"] is None
    assert row["observed_bytes"] == 2 * 1024 * 1024
    assert row["body_truncated"] and not row["body_complete"]
    assert row["sample_sha256"] == hashlib.sha256(row["body"].encode()).hexdigest()
