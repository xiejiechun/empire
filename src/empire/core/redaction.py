"""One credential redactor for diagnostics, UI snapshots and operational records.

Structured values must be redacted before serialization. Mapping keys are schema /
identity, not free text; replacing characters in a serialized document is unsafe.
"""

from __future__ import annotations

import json
import logging
import re
from itertools import islice
from urllib.parse import parse_qsl, quote, quote_plus, urlencode, urlsplit, urlunsplit

REDACTED = "[REDACTED]"
SECRET_KEY = re.compile(
    r"password|passwd|pwd|secret|token|authorization|cookie|api.?key|credential|access.?key|session.?id",
    re.I,
)
URL_PATTERN = re.compile(r"(?:https?|socks5h?|mysql(?:\+\w+)?|rediss?)://[^\s<>]+", re.I)
HEADER_PATTERN = re.compile(
    r"(?im)\b(authorization|proxy-authorization|cookie|set-cookie)\s*:\s*[^\r\n]+"
)
ASSIGNMENT_PATTERN = re.compile(
    r'''(?ix)(["']?(?:password|passwd|pwd|secret|(?:access[_-]?)?token|api[_-]?key|credential|session[_-]?id|(?:proxy[_-]?)?authorization|(?:set[_-]?)?cookie)["']?\s*[:=]\s*)(?:"(?:\\.|[^"\\\r\n])*(?:"|$)|'(?:\\.|[^'\\\r\n])*(?:'|$)|[^\s,;&}\]]+)'''
)


def clip_text(value: str, limit: int | None) -> str:
    return value if limit is None else value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


class Redactor:
    def __init__(self, secrets=()):
        variants = set()
        for item in secrets:
            if item:
                raw = str(item)
                variants.update((raw, quote(raw, safe=""), quote_plus(raw),
                                 json.dumps(raw, ensure_ascii=False)[1:-1],
                                 json.dumps(raw, ensure_ascii=True)[1:-1], repr(raw)[1:-1]))
        self.secrets = tuple(sorted(variants, key=len, reverse=True))

    @classmethod
    def from_config(cls, cfg: dict):
        return cls(cfg.get(section, {}).get("password") for section in ("redis", "mysql"))

    @staticmethod
    def _url(value):
        # Remove userinfo before parsing: literal @, quotes or URL delimiters in
        # malformed credentials must not turn a password into a visible path.
        scheme, remainder = value.split("://", 1)
        if "@" in remainder:
            remainder = remainder.rsplit("@", 1)[-1]
        try:
            url = urlsplit(scheme + "://" + remainder)
            query = [(key, REDACTED if SECRET_KEY.search(key) else val)
                     for key, val in parse_qsl(url.query, keep_blank_values=True)]
            return urlunsplit((url.scheme, url.netloc, url.path, urlencode(query), ""))
        except (ValueError, TypeError):
            return "[invalid URL]"

    def text(self, value, limit: int | None = None) -> str:
        text = str(value)
        text = URL_PATTERN.sub(lambda match: self._url(match.group()), text)
        text = HEADER_PATTERN.sub(lambda match: match.group(1) + ": " + REDACTED, text)
        text = ASSIGNMENT_PATTERN.sub(lambda match: match.group(1) + REDACTED, text)
        for secret in self.secrets:
            text = text.replace(secret, REDACTED)
        return clip_text(text, limit)

    def value(self, value, *, max_depth=40, max_items=None, max_nodes=None,
              max_bytes=None, text_limit=None):
        """Copy/redact values while preserving keys, types and optional size bounds."""
        nodes, remaining = max_nodes, max_bytes

        def visit(item, depth):
            nonlocal nodes, remaining
            if (nodes is not None and nodes <= 0) or (remaining is not None and remaining <= 0):
                return "[size limited]"
            if nodes is not None:
                nodes -= 1
            if depth >= max_depth:
                return "[depth limited]"
            if isinstance(item, dict):
                return {key: REDACTED if SECRET_KEY.search(str(key)) else visit(val, depth + 1)
                        for key, val in islice(item.items(), max_items)}
            if isinstance(item, (list, tuple)):
                return [visit(val, depth + 1) for val in islice(item, max_items)]
            if item is None or isinstance(item, (int, float, bool)):
                return item
            limit = min(text_limit, remaining) if text_limit is not None and remaining is not None else (
                text_limit if remaining is None else remaining)
            safe = self.text(item, limit)
            if remaining is not None:
                remaining -= len(safe.encode())
            return safe

        return visit(value, 0)


def redact(message: object, cfg: dict) -> str:
    return Redactor.from_config(cfg).text(message)


class RedactingFormatter(logging.Formatter):
    def __init__(self, cfg: dict) -> None:
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")
        self.redactor = Redactor.from_config(cfg)

    def format(self, record: logging.LogRecord) -> str:
        return self.redactor.text(super().format(record))
