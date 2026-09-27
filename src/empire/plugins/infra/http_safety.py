"""Untrusted response metadata and redirect credential boundaries."""
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from math import ceil
from urllib.parse import urlsplit

import httpx

# Redis Lua represents numbers as doubles. Keep deadlines exact and return only
# bounded permit waits; an astronomic, but syntactically valid, delay fails closed.
MAX_COOLDOWN_MS = 2**53 - 1
MAX_DELAY_SECONDS = MAX_COOLDOWN_MS // 1000
SENSITIVE_HEADERS = ("authorization", "proxy-authorization", "cookie")


@dataclass(frozen=True)
class RetryAfter:
    milliseconds: int
    invalid: bool = False
    saturated: bool = False


def parse_retry_after(value: str | None, *, fallback: float = 30) -> RetryAfter:
    if value:
        value = value.strip()
        if value and all("0" <= char <= "9" for char in value):
            digits = value.lstrip("0") or "0"
            ceiling = str(MAX_DELAY_SECONDS)
            if len(digits) > len(ceiling) or (len(digits) == len(ceiling) and digits > ceiling):
                return RetryAfter(MAX_COOLDOWN_MS, saturated=True)
            return RetryAfter(int(digits) * 1000)
        try:
            date = parsedate_to_datetime(value)
            if date.tzinfo is None:
                date = date.replace(tzinfo=UTC)
            seconds = max(0, (date - datetime.now(UTC)).total_seconds())
            return RetryAfter(ceil(seconds * 1000))
        except (ValueError, TypeError, OverflowError):
            pass
    return RetryAfter(ceil(fallback * 1000), invalid=bool(value))


def origin(url):
    try:
        parsed = urlsplit(str(url))
        # DNS-equivalent names (including a terminal dot) are not necessarily the
        # same web origin. Explicit port zero must not become the default port.
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower()
        port = parsed.port if parsed.port is not None else {"http": 80, "https": 443}[parsed.scheme]
        return parsed.scheme.lower(), host, port
    except (ValueError, UnicodeError, KeyError):
        # Parser errors can otherwise quote an untrusted authority/port verbatim.
        raise ValueError("采集重定向地址无效") from None


def redirect_options(source, target, options):
    """Credentials never return after a chain crosses an origin boundary."""
    previous, following = origin(source), origin(target)
    if previous[0] == "https" and following[0] == "http":
        # No URL or header interpolation: rejected targets can contain secrets.
        raise ValueError("采集请求禁止从 HTTPS 重定向到 HTTP")
    if previous != following:
        headers = httpx.Headers(options.get("headers"))
        for name in (*SENSITIVE_HEADERS, "host"):
            headers.pop(name, None)
        options["headers"] = headers
        options["auth"] = None
        options.pop("cookies", None)
        # Applied AFTER build_request too, because defaults and the shared client
        # cookie jar can otherwise reintroduce credentials removed above.
        options["strip_credentials"] = True
