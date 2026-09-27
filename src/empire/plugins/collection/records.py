"""Bounded, Redis-only operational records; never part of the business archive."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from empire.build_info import build_identity
from empire.contracts.plugin import PluginManifest
from empire.core.redaction import Redactor, clip_text

ERROR_LIMIT = 300
ARCHIVE_LIMIT = 100
BODY_LIMIT = 64 * 1024
TEXT_LIMIT = 4096

# A retry after an ambiguous Redis result replaces the same ID rather than duplicating it.
APPEND = """
local old = redis.call('LRANGE', KEYS[1], 0, -1)
for _, raw in ipairs(old) do
    local ok, row = pcall(cjson.decode, raw)
    if ok and row['id'] == ARGV[2] then redis.call('LREM', KEYS[1], 0, raw) end
end
redis.call('LPUSH', KEYS[1], ARGV[1])
redis.call('LTRIM', KEYS[1], 0, tonumber(ARGV[3]) - 1)
redis.call('INCR', KEYS[2])
return 1
"""

# Compare exact IDs inside one atomic operation; new/unreviewed records survive.
CLEAR = """
local selected = {}
for _, id in ipairs(ARGV) do selected[id] = true end
local removed = 0
for _, raw in ipairs(redis.call('LRANGE', KEYS[1], 0, -1)) do
    local ok, row = pcall(cjson.decode, raw)
    if ok and selected[row['id']] then
        removed = removed + redis.call('LREM', KEYS[1], 0, raw)
    end
end
if removed > 0 then redis.call('INCR', KEYS[2]) end
return removed
"""

# Decode only the requested page inside Redis; full bodies never cross the connection for a list view.
LIST_ERROR_SUMMARIES = """
local revision = redis.call('GET', KEYS[2]) or '0'
local total = redis.call('LLEN', KEYS[1])
if ARGV[1] == revision then return {revision, tostring(total), '0'} end
local offset = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
if total > 0 and offset >= total then offset = math.floor((total - 1) / limit) * limit end
local result = {revision, tostring(total), '1', tostring(offset)}
for _, raw in ipairs(redis.call('LRANGE', KEYS[1], offset, offset + limit - 1)) do
    local ok, row = pcall(cjson.decode, raw)
    if ok then
        table.insert(result, cjson.encode({id=row['id'], project_id=row['project_id'],
            created_at=row['created_at'], stage=row['stage'], error=row['error'],
            status_code=row['status_code'] or cjson.null}))
    end
end
return result
"""

GET_ERROR = """
for _, raw in ipairs(redis.call('LRANGE', KEYS[1], 0, -1)) do
    local ok, row = pcall(cjson.decode, raw)
    if ok and row['id'] == ARGV[1] then return raw end
end
return false
"""


class RecordsPlugin:
    manifest = PluginManifest(
        "collection.records", "采集诊断与归档记录", requires=("redis.store",),
        provides=("collection.records",),
        description="错误响应每项目 300 条、归档记录每项目 100 条；仅保存在 Redis",
    )

    def __init__(self, secrets=()):
        self.redis = None
        self.redactor = Redactor(secrets)
        self.stats = {"status": "stopped"}
        self.version = build_identity()

    async def start(self, context):
        self.redis = context.get("redis.store")
        self.stats["status"] = "ok"
        return {"collection.records": self}

    def _key(self, kind, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", project_id):
            raise ValueError("Invalid collection project ID")
        return f"{self.redis.prefix}:collection:{kind}:{project_id}"

    def _revision_key(self, kind, project_id):
        return self._key(f"{kind}-revision", project_id)

    def sanitize_text(self, value, limit=TEXT_LIMIT):
        return self.redactor.text(value, limit)

    def _bounded_metadata(self, metadata):
        value = self.redactor.value(metadata or {}, max_depth=5, max_items=30,
                                    max_nodes=128, max_bytes=16384, text_limit=TEXT_LIMIT)
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        if len(serialized.encode()) > 8192:
            return {"excerpt": clip_text(serialized, 8000), "truncated": True}
        return value

    def _body(self, raw_body, *, complete=True, observed_bytes=None, body_sha256=None):
        raw = raw_body if isinstance(raw_body, bytes) else str(raw_body or "").encode("utf-8")
        # Read only a bounded prefix into a decoded diagnostic string.
        prefix = raw[:BODY_LIMIT * 2]
        try:
            decoded = prefix.decode("utf-8")
        except UnicodeDecodeError:
            decoded = prefix.decode("gb18030", errors="replace")
        try:
            structured = json.loads(decoded)
        except (ValueError, RecursionError):
            safe = self.sanitize_text(decoded, BODY_LIMIT * 2)
        else:
            try:
                safe = json.dumps(self.redactor.value(structured), ensure_ascii=False)
            except RecursionError:
                safe = "[JSON nesting too deep for a diagnostic sample]"
        # No second redaction over serialized JSON: that could corrupt its syntax.
        body = clip_text(safe, BODY_LIMIT)
        return {
            "body": body,
            "body_truncated": (not complete or (observed_bytes or 0) > len(raw)
                               or len(raw) > len(prefix) or len(safe.encode()) > BODY_LIMIT),
            "body_complete": bool(complete),
            "observed_bytes": max(len(raw), observed_bytes or 0),
            "original_bytes": (observed_bytes if observed_bytes is not None else len(raw)) if complete else None,
            "original_sha256": (body_sha256 or hashlib.sha256(raw).hexdigest()) if complete else None,
            "sample_sha256": hashlib.sha256(body.encode()).hexdigest(),
        }

    async def _append(self, kind, project_id, record, limit):
        await self.redis.client.eval(
            APPEND, 2, self._key(kind, project_id), self._revision_key(kind, project_id),
            json.dumps(record, ensure_ascii=False, separators=(",", ":")), record["id"], limit,
        )
        return record

    async def add_error(self, project_id, *, stage, error, raw_body=None, request_url=None,
                        status_code=None, metadata=None, record_id=None, raw_body_complete=True,
                        observed_bytes=None, body_sha256=None):
        record = {
            "id": self.sanitize_text(record_id or uuid4().hex, 256),
            "project_id": project_id, "created_at": datetime.now(UTC).isoformat(),
            "version": self.version, "stage": self.sanitize_text(stage, 128),
            "error": self.sanitize_text(error),
            "request_url": self.sanitize_text(request_url or "", 2048),
            "status_code": status_code if type(status_code) is int else None,
            "metadata": self._bounded_metadata(metadata),
            **self._body(raw_body, complete=raw_body_complete, observed_bytes=observed_bytes,
                         body_sha256=body_sha256),
        }
        return await self._append("errors", project_id, record, ERROR_LIMIT)

    async def list_error_summaries(self, project_id, offset=0, limit=50, known_revision=None):
        if (type(offset) is not int or type(limit) is not int or not 0 <= offset < ERROR_LIMIT
                or not 1 <= limit <= 100 or (known_revision is not None
                and (not isinstance(known_revision, str) or len(known_revision) > 32))):
            raise ValueError("Invalid error record page")
        result = await self.redis.client.eval(
            LIST_ERROR_SUMMARIES, 2, self._key("errors", project_id),
            self._revision_key("errors", project_id), known_revision or "", offset, limit)
        revision, total, changed = str(result[0]), int(result[1]), result[2] == "1"
        return {"revision": revision, "total": total, "changed": changed,
                "offset": int(result[3]) if changed else offset, "limit": limit,
                "rows": [json.loads(raw) for raw in result[4:]] if changed else []}

    async def get_error(self, project_id, record_id):
        if not isinstance(record_id, str) or not record_id or len(record_id.encode()) > 256:
            raise ValueError("Invalid error record ID")
        raw = await self.redis.client.eval(
            GET_ERROR, 1, self._key("errors", project_id), record_id)
        return json.loads(raw) if raw else None

    async def clear_errors(self, project_id, record_ids):
        """Call only after the selected failures have been handled and verified."""
        if not record_ids:
            return 0
        ids = list(dict.fromkeys(str(ident) for ident in record_ids))
        if len(ids) > ERROR_LIMIT or any(len(ident.encode()) > 256 for ident in ids):
            raise ValueError("Invalid error record selection")
        return int(await self.redis.client.eval(
            CLEAR, 2, self._key("errors", project_id), self._revision_key("errors", project_id), *ids))

    async def add_archive(self, project_id, record):
        # Operational metadata only. Successful responses never enter this list.
        safe = self._bounded_metadata({key: value for key, value in record.items()
                                       if key not in {"body", "raw_body", "raw_response", "raw_payload"}})
        safe.update(id=self.sanitize_text(record.get("id") or uuid4().hex, 256),
                    project_id=project_id, created_at=datetime.now(UTC).isoformat(),
                    version=self.version)
        return await self._append("archives", project_id, safe, ARCHIVE_LIMIT)

    async def list_archives(self, project_id):
        return [json.loads(raw) for raw in await self.redis.client.lrange(
            self._key("archives", project_id), 0, ARCHIVE_LIMIT - 1,
        )]

    async def stop(self):
        self.stats["status"] = "stopped"

    def health(self):
        return dict(self.stats)
