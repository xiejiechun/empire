"""Bounded, Redis-only operational records; never part of the business archive."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from itertools import islice
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit
from uuid import uuid4

from empire.contracts.plugin import PluginManifest

ERROR_LIMIT = 300
ARCHIVE_LIMIT = 100
BODY_LIMIT = 64 * 1024
TEXT_LIMIT = 4096
REDACTED = "[REDACTED]"
SECRET_KEY = re.compile(
    r"password|passwd|pwd|secret|token|authorization|cookie|api.?key|credential|access.?key|session.?id",
    re.I,
)
URL_PATTERN = re.compile(r"(?:https?|mysql(?:\+\w+)?|rediss?)://[^\s<>\"']+", re.I)

# A retry after an ambiguous Redis result replaces the same ID rather than duplicating it.
APPEND = """
local old = redis.call('LRANGE', KEYS[1], 0, -1)
for _, raw in ipairs(old) do
    local ok, row = pcall(cjson.decode, raw)
    if ok and row['id'] == ARGV[2] then redis.call('LREM', KEYS[1], 0, raw) end
end
redis.call('LPUSH', KEYS[1], ARGV[1])
redis.call('LTRIM', KEYS[1], 0, tonumber(ARGV[3]) - 1)
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
return removed
"""


def project_id_for(source: str = "", job_key: str = "") -> str:
    """The source's registered collection project owns all its operational records."""
    if job_key == "sina-universe-v1" or (source == "sina" and not job_key):
        return "sina-stocks"
    if job_key == "sina-news-v1":
        return "sina-news"
    if job_key == "cninfo-calendar-v1":
        return "cninfo-calendar"
    value = str(job_key or source or "unknown")
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value):
        return value
    return "project-" + hashlib.sha256(value.encode()).hexdigest()[:24]


def _clip(value: str, limit: int) -> str:
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


class RecordsPlugin:
    manifest = PluginManifest(
        "collection.records", "采集诊断与归档记录", requires=("redis.store",),
        provides=("collection.records",),
        description="错误响应每项目 300 条、归档记录每项目 100 条；仅保存在 Redis",
    )

    def __init__(self, secrets=()):
        self.redis = None
        variants = {variant for item in secrets if item
                    for variant in (str(item), quote(str(item), safe=""), quote_plus(str(item)))}
        self.secrets = tuple(sorted(variants, key=len, reverse=True))
        self.stats = {"status": "stopped"}
        try:
            self.version = version("empire-research")
        except PackageNotFoundError:
            self.version = "development"

    async def start(self, context):
        self.redis = context.get("redis.store")
        self.stats["status"] = "ok"
        return {"collection.records": self}

    def _key(self, kind, project_id):
        if not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", project_id):
            raise ValueError("Invalid collection project ID")
        return f"{self.redis.prefix}:collection:{kind}:{project_id}"

    def _url(self, value):
        try:
            url = urlsplit(value)
            host = url.netloc.rsplit("@", 1)[-1]
            query = [(key, REDACTED if SECRET_KEY.search(key) else val)
                     for key, val in parse_qsl(url.query, keep_blank_values=True)]
            return urlunsplit((url.scheme, host, url.path, urlencode(query), ""))
        except (ValueError, TypeError):
            return "[invalid URL]"

    def sanitize_text(self, value, limit=TEXT_LIMIT):
        text = str(value)
        for secret in self.secrets:
            text = text.replace(secret, REDACTED)
        text = URL_PATTERN.sub(lambda match: self._url(match.group()), text)
        # HTTP credential headers may contain spaces, commas and semicolons.
        text = re.sub(
            r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\r\n]+",
            lambda match: match.group(1) + ": " + REDACTED, text,
        )
        text = re.sub(
            r'''(?ix)(["']?(?:password|passwd|pwd|secret|(?:access[_-]?)?token|api[_-]?key|credential|session[_-]?id|(?:proxy[_-]?)?authorization|(?:set[_-]?)?cookie)["']?\s*[:=]\s*)(?:"[^"\r\n]*"|'[^'\r\n]*'|[^\s,;&}\]]+)''',
            lambda match: match.group(1) + REDACTED, text,
        )
        return _clip(text, limit)

    def _safe(self, value, depth=0, budget=None):
        budget = budget if budget is not None else [16384, 128]
        if budget[0] <= 0 or budget[1] <= 0:
            return "[size limited]"
        budget[1] -= 1
        if depth >= 5:
            return "[depth limited]"
        if isinstance(value, dict):
            return {
                self.sanitize_text(key, 128): REDACTED if SECRET_KEY.search(str(key)) else self._safe(item, depth + 1, budget)
                for key, item in islice(value.items(), 30)
            }
        if isinstance(value, (list, tuple)):
            return [self._safe(item, depth + 1, budget) for item in value[:30]]
        if value is None or isinstance(value, (int, float, bool)):
            return value
        safe = self.sanitize_text(value, min(TEXT_LIMIT, budget[0]))
        budget[0] -= len(safe.encode())
        return safe

    def _bounded_metadata(self, metadata):
        value = self._safe(metadata or {})
        serialized = json.dumps(value, ensure_ascii=False, default=str)
        if len(serialized.encode()) > 8192:
            return {"excerpt": _clip(serialized, 8000), "truncated": True}
        return value

    def _body(self, raw_body):
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
            def redact_json(value):
                if isinstance(value, dict):
                    return {key: REDACTED if SECRET_KEY.search(key) else redact_json(item)
                            for key, item in value.items()}
                if isinstance(value, list):
                    return [redact_json(item) for item in value]
                if isinstance(value, str):
                    return self.sanitize_text(value, BODY_LIMIT * 2)
                return value

            try:
                safe = json.dumps(redact_json(structured), ensure_ascii=False)
            except RecursionError:
                safe = "[JSON nesting too deep for a diagnostic sample]"
        body = self.sanitize_text(safe, BODY_LIMIT)
        return {
            "body": body,
            "body_truncated": len(raw) > len(prefix) or len(safe.encode()) > BODY_LIMIT,
            "original_bytes": len(raw),
            "original_sha256": hashlib.sha256(raw).hexdigest(),
        }

    async def _append(self, kind, project_id, record, limit):
        await self.redis.client.eval(
            APPEND, 1, self._key(kind, project_id),
            json.dumps(record, ensure_ascii=False, separators=(",", ":")), record["id"], limit,
        )
        return record

    async def add_error(self, project_id, *, stage, error, raw_body=None, request_url=None,
                        status_code=None, metadata=None, record_id=None):
        record = {
            "id": self.sanitize_text(record_id or uuid4().hex, 256),
            "project_id": project_id, "created_at": datetime.now(UTC).isoformat(),
            "version": self.version, "stage": self.sanitize_text(stage, 128),
            "error": self.sanitize_text(error),
            "request_url": self.sanitize_text(request_url or "", 2048),
            "status_code": status_code if type(status_code) is int else None,
            "metadata": self._bounded_metadata(metadata), **self._body(raw_body),
        }
        return await self._append("errors", project_id, record, ERROR_LIMIT)

    async def list_errors(self, project_id):
        return [json.loads(raw) for raw in await self.redis.client.lrange(
            self._key("errors", project_id), 0, ERROR_LIMIT - 1,
        )]

    async def clear_errors(self, project_id, record_ids):
        """Call only after the selected failures have been handled and verified."""
        if not record_ids:
            return 0
        ids = list(dict.fromkeys(str(ident) for ident in record_ids))
        if len(ids) > ERROR_LIMIT or any(len(ident.encode()) > 256 for ident in ids):
            raise ValueError("Invalid error record selection")
        return int(await self.redis.client.eval(CLEAR, 1, self._key("errors", project_id), *ids))

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
