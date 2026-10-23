"""Native target contract shared by source protocols and downloader infrastructure."""
import re
from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass(frozen=True)
class StreamTarget:
    host: str
    port: int
    site_url: str
    allowed_domains: tuple[str, ...]

    def __post_init__(self):
        if (not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", self.host)
                or type(self.port) is not int or not 1 <= self.port <= 65535):
            raise ValueError("Invalid native destination")
        parsed = urlsplit(self.site_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname
                or parsed.path not in ("", "/") or parsed.query or parsed.fragment
                or parsed.username is not None or parsed.password is not None):
            raise ValueError("Native site identity cannot contain credentials or query")
        host = self.host.lower().rstrip(".")
        if not any(host == domain.lower() or host.endswith("." + domain.lower())
                   for domain in self.allowed_domains if domain):
            raise ValueError("Native destination domain is not declared")

