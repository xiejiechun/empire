from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx

from empire.contracts.plugin import PluginContext, PluginManifest

PERMIT_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local next_at = tonumber(redis.call('HGET', KEYS[1], 'next') or '0')
local cooldown = tonumber(redis.call('HGET', KEYS[1], 'cooldown') or '0')
local wait = math.max(next_at, cooldown) - now
if wait > 0 then return wait end
redis.call('HSET', KEYS[1], 'next', now + tonumber(ARGV[1]))
return 0
"""

COOLDOWN_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local old = tonumber(redis.call('HGET', KEYS[1], 'cooldown') or '0')
local until_at = math.max(old, now + tonumber(ARGV[1]))
redis.call('HSET', KEYS[1], 'cooldown', until_at)
return until_at
"""


def normalize_host(host: str) -> str:
    return host.rstrip(".").encode("idna").decode("ascii").lower()


def matches(host: str, domain: str) -> bool:
    return host == domain or host.endswith("." + domain)


@dataclass(frozen=True)
class RateGroup:
    name: str
    domains: tuple[str, ...]
    min_interval_ms: int = 2000
    max_concurrency: int = 1


class RateRules:
    def __init__(self, config: dict) -> None:
        self.groups = []
        seen: set[str] = set()
        for name, values in config.items():
            domains = tuple(normalize_host(d) for d in values["domains"])
            if any(domain in seen for domain in domains):
                raise ValueError("A domain cannot belong to multiple rate groups")
            seen.update(domains)
            group = RateGroup(name, domains, int(values.get("min_interval_ms", 2000)),
                              int(values.get("max_concurrency", 1)))
            if group.min_interval_ms < 1 or group.max_concurrency < 1:
                raise ValueError("Rate limit settings must be positive")
            self.groups.append(group)

    def resolve(self, url: str, allowed_domains: tuple[str, ...]) -> RateGroup:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("Only HTTP(S) collection URLs are supported")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("Credentials in source URLs are not supported")
        host = normalize_host(parsed.hostname)
        if not any(matches(host, normalize_host(d)) for d in allowed_domains):
            raise ValueError(f"Source domain is not declared: {host}")
        candidates = [(len(d), g) for g in self.groups for d in g.domains if matches(host, d)]
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        return RateGroup(f"host:{host}", (host,))


def retry_after_seconds(value: str | None, *, fallback: float = 30) -> float:
    if value:
        try:
            return max(0, float(value))
        except ValueError:
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=UTC)
                return max(0, (date - datetime.now(UTC)).total_seconds())
            except (ValueError, TypeError, OverflowError):
                pass
    return fallback


class HttpService:
    def __init__(self, redis, prefix: str, groups: dict, *, transport=None, records=None) -> None:
        self.redis = redis
        self.prefix = prefix
        self.records = records
        self.rules = RateRules(groups)
        self.slots: dict[str, asyncio.Semaphore] = {}
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10), follow_redirects=False, transport=transport,
            headers={"User-Agent": "EmpireResearch/0.1 personal-research"},
        )
        self.stats: dict[str, dict] = {}
        self.inflight: set[asyncio.Task] = set()
        self.closed = False

    async def _record_failure(self, project_id, method, url, error, response=None, attempt=1):
        if self.records is None or getattr(error, "diagnostic_recorded", False):
            return
        await self.records.add_error(
            project_id, stage="http", error=str(error),
            raw_body=response.content if response is not None else None,
            request_url=str(response.url) if response is not None else str(url),
            status_code=response.status_code if response is not None else None,
            metadata={"method": method.upper(), "attempt": attempt},
        )
        error.diagnostic_recorded = True

    async def _one(self, method: str, url: str, allowed: tuple[str, ...], **kwargs):
        group = self.rules.resolve(url, allowed)
        slot = self.slots.setdefault(group.name, asyncio.Semaphore(group.max_concurrency))
        stats = self.stats.setdefault(group.name, {"requests": 0, "waiting": 0, "last_status": None})
        key = f"{self.prefix}:rate:{group.name}"
        while True:
            group = self.rules.resolve(url, allowed)
            await slot.acquire()
            granted = False
            try:
                delay = int(await self.redis.eval(PERMIT_LUA, 1, key, group.min_interval_ms))
                if delay <= 0:
                    granted = True
                    stats["requests"] += 1
                    response = await self.client.request(method, url, **kwargs)
                    stats["last_status"] = response.status_code
                    if response.status_code == 429:
                        seconds = retry_after_seconds(response.headers.get("Retry-After"))
                        await self.redis.eval(COOLDOWN_LUA, 1, key, int(seconds * 1000))
                        stats["cooldown_seconds"] = seconds
                    return response
            finally:
                slot.release()
            if not granted:
                stats["waiting"] += 1
                try:
                    await asyncio.sleep(delay / 1000)
                finally:
                    stats["waiting"] -= 1

    async def request(
        self, method: str, url: str, *, allowed_domains: tuple[str, ...],
        max_retries: int = 2, max_redirects: int = 5, total_timeout: float = 120,
        project_id: str | None = None,
        **kwargs,
    ) -> httpx.Response:
        if self.closed:
            raise RuntimeError("HTTP plugin has stopped")
        if method.upper() not in ("GET", "HEAD", "POST"):
            raise ValueError("Unsupported collection request method")
        if self.records is not None and not project_id:
            raise ValueError("采集 HTTP 请求必须声明 project_id，用于按项目保存错误记录")
        task = asyncio.current_task()
        self.inflight.add(task)
        retries = redirects = 0
        response = None
        try:
            async with asyncio.timeout(total_timeout):
                while True:
                    response = None
                    try:
                        response = await self._one(method, url, allowed_domains, **kwargs)
                    except httpx.TransportError as exc:
                        await self._record_failure(project_id, method, url, exc, attempt=retries + 1)
                        if retries >= max_retries:
                            raise
                        retries += 1
                        await asyncio.sleep(2 ** (retries - 1))
                        continue
                    if response.status_code in (301, 302, 303, 307, 308) and "location" in response.headers:
                        if redirects >= max_redirects:
                            raise httpx.TooManyRedirects("Collection redirect limit reached")
                        target = urljoin(str(response.url), response.headers["location"])
                        self.rules.resolve(target, allowed_domains)
                        if urlsplit(target).netloc != urlsplit(url).netloc:
                            headers = kwargs.get("headers", {})
                            kwargs["headers"] = {k: v for k, v in headers.items()
                                                 if k.lower() not in ("authorization", "cookie")}
                        kwargs.pop("params", None)
                        if response.status_code == 303 or (
                            response.status_code in (301, 302) and method.upper() == "POST"
                        ):
                            method = "GET"
                            for field in ("json", "data", "content"):
                                kwargs.pop(field, None)
                        url = target
                        redirects += 1
                        continue
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        await self._record_failure(project_id, method, url, exc, response, retries + 1)
                        if response.status_code in (429, 502, 503, 504) and retries < max_retries:
                            retries += 1
                            await asyncio.sleep(2 ** (retries - 1))
                            continue
                        raise
                    return response
        except Exception as exc:
            await self._record_failure(project_id, method, url, exc, response, retries + 1)
            raise
        finally:
            self.inflight.discard(task)

    async def settings(self):
        return [{"name": g.name, "domains": list(g.domains),
                 "min_interval_ms": g.min_interval_ms, "max_concurrency": g.max_concurrency,
                 **self.stats.get(g.name, {})} for g in self.rules.groups]

    async def configure_interval(self, name, interval_ms):
        if type(interval_ms) is not int or not 100 <= interval_ms <= 60000:
            raise ValueError("网站请求间隔须为 100～60000 毫秒")
        if name not in {g.name for g in self.rules.groups}:
            raise ValueError("未知网站组")
        values = {g.name: g.min_interval_ms for g in self.rules.groups}
        values[name] = interval_ms
        await self.redis.set(f"{self.prefix}:collection:site-intervals:v1", json.dumps(values))
        self.rules.groups = [replace(g, min_interval_ms=interval_ms) if g.name == name else g
                             for g in self.rules.groups]
        return "网站间隔已保存，对下一次申请的请求生效；已有冷却时间继续保留"

    async def close(self) -> None:
        self.closed = True
        tasks = [t for t in self.inflight if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await self.client.aclose()


class HttpPlugin:
    manifest = PluginManifest(
        "infra.http", "共享 HTTP / 站点频控", requires=("redis.store", "collection.records"),
        provides=("http.fetch",), description="跨采集插件共享域名组频率、重试和冷却",
    )

    def __init__(self, groups: dict) -> None:
        self.groups = groups
        self.service: HttpService | None = None

    async def start(self, context: PluginContext) -> dict:
        store = context.get("redis.store")
        self.service = HttpService(store.client, store.prefix, self.groups,
                                   records=context.get("collection.records"))
        raw = await store.client.get(f"{store.prefix}:collection:site-intervals:v1")
        if raw:
            values = json.loads(raw)
            for group in self.service.rules.groups[:]:
                if group.name in values:
                    interval = values[group.name]
                    if type(interval) is not int or not 100 <= interval <= 60000:
                        raise ValueError("已保存的网站间隔无效")
                    self.service.rules.groups = [replace(g, min_interval_ms=interval)
                        if g.name == group.name else g for g in self.service.rules.groups]
        return {"http.fetch": self.service}

    async def stop(self) -> None:
        if self.service:
            await self.service.close()
            self.service = None

    def health(self) -> dict:
        return {"groups": self.service.stats if self.service else {}}
