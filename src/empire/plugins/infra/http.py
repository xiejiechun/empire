from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, replace
from urllib.parse import urljoin, urlsplit

import httpx

from empire.contracts.download import FilePolicy, ResponsePolicy
from empire.contracts.download_settings import (
    DEFAULTS,
    MAX_PARALLEL_DOWNLOADS,
    PROFILE_FIELDS,
    local_download_options,
)
from empire.contracts.plugin import PluginContext, PluginManifest
from empire.core.config import user_data_dir
from empire.plugins.infra.capacity import capacity
from empire.plugins.infra.download_storage import DownloadStorage
from empire.plugins.infra.http_safety import (
    MAX_COOLDOWN_MS,
    parse_retry_after,
    redirect_options,
)
from empire.plugins.infra.request_activity import RequestRate
from empire.plugins.infra.resources import ByteBudget
from empire.plugins.infra.response_reader import DownloadLimitError, read_response
from empire.plugins.infra.routing import USE_PROXY, routed_request, site_policy
from empire.plugins.infra.settings import SettingsStore

COOLDOWN_LUA = """
local t = redis.call('TIME')
local now = tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
local old = tonumber(redis.call('HGET', KEYS[1], 'cooldown') or '0')
local until_at = math.min(9007199254740991, math.max(old, now + tonumber(ARGV[1])))
redis.call('HSET', KEYS[1], 'cooldown', string.format('%.0f', until_at))
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
    proxy_interval_ms: int = 2000
    total_interval_ms: int = 500
    scaling_mode: str = "fixed"
    max_rps: int = 0


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
                              int(values.get("max_concurrency", 1)),
                              int(values.get("proxy_interval_ms", values.get("min_interval_ms", 2000))),
                              int(values.get("total_interval_ms", min(500, values.get("min_interval_ms", 2000)))),
                              values.get("scaling_mode", "fixed"), int(values.get("max_rps", 0)))
            if min(group.min_interval_ms, group.proxy_interval_ms, group.total_interval_ms) < 1 or not 0 <= group.max_concurrency <= MAX_PARALLEL_DOWNLOADS:
                raise ValueError("Rate limit settings must be positive")
            if group.scaling_mode not in ("fixed", "auto") or not 0 <= group.max_rps <= 100:
                raise ValueError("Invalid automatic scaling limits")
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


class HttpService:
    def __init__(self, redis, prefix: str, groups: dict, *, transport=None, records=None, settings=None, pool=None, resources=None) -> None:
        self.redis = redis
        self.prefix = prefix
        self.records = records
        self.setting_store = settings
        self.pool = pool
        resources = {**DEFAULTS, **(resources or {})}
        self.resource_values = dict(resources)
        global_limit = resources["max_parallel_downloads"]
        if type(global_limit) is not int or not 1 <= global_limit <= MAX_PARALLEL_DOWNLOADS:
            raise ValueError(f"全局最多同时下载须为 1～{MAX_PARALLEL_DOWNLOADS} 的整数")
        self.buffer_budget = ByteBudget(resources["buffer_budget_bytes"])
        self.storage = DownloadStorage(resources.get("download_directory", user_data_dir() / "downloads"),
            quota_bytes=resources["download_quota_bytes"],
            min_free_bytes=resources["disk_free_margin_bytes"], concurrency=resources["file_concurrency"])
        self.responses = set()
        self.global_limit = global_limit
        self.global_active = 0
        self.global_peak = 0
        self.admission_changed = asyncio.Event()
        self.active = {}
        self.direct_active = {}
        self.recent_requests = defaultdict(RequestRate)
        self.rules = RateRules(groups)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(30, connect=10), follow_redirects=False, transport=transport, trust_env=False,
            headers={"User-Agent": "EmpireResearch/0.1 personal-research"},
        )
        self.stats: dict[str, dict] = {}
        self.inflight: set[asyncio.Task] = set()
        self.closed = False

    async def _record_failure(self, project_id, method, url, error, response=None, attempt=1):
        if self.records is None or getattr(error, "diagnostic_recorded", False):
            return
        incomplete = isinstance(error, DownloadLimitError)
        extra = {"raw_body_complete": False, "observed_bytes": error.observed_bytes} if incomplete else {}
        await self.records.add_error(
            project_id, stage="http", error=str(error),
            raw_body=error.sample if incomplete else response.content if response is not None else None,
            request_url=str(response.url) if response is not None else str(url),
            status_code=error.status_code if incomplete else response.status_code if response is not None else None,
            metadata={"method": method.upper(), "attempt": attempt}, **extra,
        )
        error.diagnostic_recorded = True

    async def _one(self, method: str, url: str, allowed: tuple[str, ...], **kwargs):
        return await routed_request(self, method, url, allowed, **kwargs)

    async def transfer(self, client, method, url, *, key, stats, policy, **kwargs):
        async def headers(response):
            if response.status_code == 429:
                await self.cooldown(key, response, stats)
        return await read_response(client, method, url, policy=policy,
                                   storage=self.storage, on_headers=headers, **kwargs)

    def response_policy(self, profile="generic"):
        size = self.resource_values[PROFILE_FIELDS[profile]]
        return ResponsePolicy(max_body_bytes=size, max_wire_bytes=size)

    def file_policy(self, *, filename, signature=b"", expected_sha256=None):
        size = self.resource_values["file_response_bytes"]
        return FilePolicy(max_body_bytes=size, max_wire_bytes=size, filename=filename,
                          signature=signature, expected_sha256=expected_sha256)

    async def request(self, method, url, *, policy=None, reservation=None, **kwargs):
        """Close the returned response after consumption; files stream to a quota'd sink."""
        task = asyncio.current_task()
        self.inflight.add(task)
        lease, file_slot = None, False
        try:
            if self.closed:
                raise RuntimeError("HTTP plugin has stopped")
            policy = policy if policy is not None else self.response_policy()
            if isinstance(policy, FilePolicy):
                ceiling = self.resource_values["file_response_bytes"]
                policy = replace(policy, max_body_bytes=min(policy.max_body_bytes, ceiling),
                                 max_wire_bytes=min(policy.max_wire_bytes, ceiling))
                await self.storage.slots.acquire()
                file_slot = True
            if reservation is not None:
                if (reservation.budget is not self.buffer_budget or reservation.released
                        or reservation.size != policy.reservation_bytes):
                    raise ValueError("响应缓冲预留与请求策略不一致")
                lease = reservation
            else:
                lease = await self.buffer_budget.reserve(policy.reservation_bytes)
            response = await self._request(method, url, policy=policy, **kwargs)
            if response.artifact is None:
                response.reservation, lease = lease, None
                self.responses.add(response)
                response.on_close = self.responses.discard
            return response
        finally:
            if lease and reservation is None:
                lease.release()
            if file_slot:
                self.storage.slots.release()
            self.inflight.discard(task)

    async def _request(
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
                        redirect_options(response.url, target, kwargs)
                        kwargs.pop("params", None)
                        if response.status_code == 303 or (
                            response.status_code in (301, 302) and method.upper() == "POST"
                        ):
                            method = "GET"
                            for field in ("json", "data", "content"):
                                kwargs.pop(field, None)
                        url = target
                        redirects += 1
                        response.close()
                        continue
                    try:
                        response.raise_for_status()
                    except httpx.HTTPStatusError as exc:
                        await self._record_failure(project_id, method, url, exc, response, retries + 1)
                        if response.status_code in (429, 502, 503, 504) and retries < max_retries:
                            retries += 1
                            response.close()
                            await asyncio.sleep(2 ** (retries - 1))
                            continue
                        raise
                    return response
        except BaseException as exc:
            try:
                if isinstance(exc, Exception):
                    await self._record_failure(project_id, method, url, exc, response, retries + 1)
            finally:
                if response is not None:
                    response.close()
            raise

    async def cooldown(self, key, response, stats):
        delay = parse_retry_after(response.headers.get("Retry-After"))
        deadline = await self.redis.eval(COOLDOWN_LUA, 1, key, delay.milliseconds)
        stats["cooldown_seconds"] = delay.milliseconds / 1000
        stats["cooldown_saturated"] = delay.saturated or deadline >= MAX_COOLDOWN_MS
        stats["cooldown_note"] = (
            "Retry-After 超出可表示范围，网站保持长期冷却，需核查来源响应"
            if stats["cooldown_saturated"] else
            "Retry-After 无效，按默认 30 秒冷却" if delay.invalid else ""
        )

    def activity_snapshot(self, name):
        stats = self.stats.get(name, {})
        return {**stats, "waiting_reasons": dict(stats.get("waiting_reasons", {}))}

    async def settings(self):
        return [{"name": g.name, "domains": list(g.domains),
                 "min_interval_ms": g.min_interval_ms, "max_concurrency": g.max_concurrency,
                 "proxy_interval_ms": g.proxy_interval_ms, "total_interval_ms": g.total_interval_ms,
                 "scaling_mode": g.scaling_mode, "max_rps": g.max_rps,
                 "active_requests": self.active.get(g.name, 0),
                 "recent_rps": self.recent_requests[g.name].rate(),
                 "global_active_requests": self.global_active,
                 "buffer_limit_bytes": self.buffer_budget.limit,
                 "buffer_reserved_bytes": self.buffer_budget.used,
                 "buffer_available_bytes": self.buffer_budget.limit - self.buffer_budget.used,
                 "response_reservation_bytes": {name: self.response_policy(name).reservation_bytes
                                                for name in PROFILE_FIELDS},
                 **capacity(g, self.pool.healthy_count() if self.pool else 0, self.global_limit),
                 **self.activity_snapshot(g.name)} for g in self.rules.groups]

    async def parallelism(self, url, allowed_domains):
        """Collectors opt in only when their pages can be independently fetched."""
        if not USE_PROXY.get() or self.pool is None:
            return 1
        await self.pool.refresh(waiting=True)
        group = self.rules.resolve(url, allowed_domains)
        healthy = self.pool.healthy_count()
        return max(1, min(healthy, capacity(group, healthy, self.global_limit)["effective_concurrency"]))

    async def configure_site(self, name, values):
        group = next((g for g in self.rules.groups if g.name == name), None)
        if group is None:
            raise ValueError("未知网站组")
        existing = {key: getattr(group, key) for key in site_policy({})}
        policy = site_policy(values, existing)
        if self.setting_store is None:
            raise RuntimeError("MySQL 配置存储未就绪")
        await self.setting_store.save("site", name, policy)
        self.rules.groups = [replace(g, **policy) if g.name == name else g for g in self.rules.groups]
        self.admission_changed.set()
        return "网站间隔已保存到 MySQL，对下一次申请的请求生效；已有冷却时间继续保留"

    async def close(self) -> None:
        self.closed = True
        tasks = [t for t in self.inflight if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for response in list(self.responses):
            response.close()
        await self.client.aclose()


class HttpPlugin:
    manifest = PluginManifest(
        "infra.http", "共享 HTTP / 站点频控",
        requires=("redis.store", "mysql.store", "collection.records", "proxy.pool", "download.settings"),
        provides=("http.fetch",), description="跨采集插件共享域名组频率、重试和冷却",
    )

    def __init__(self, groups: dict, resources=None) -> None:
        self.groups = groups
        self.local_options = local_download_options(resources or {})
        self.download_settings = None
        self.service: HttpService | None = None

    async def start(self, context: PluginContext) -> dict:
        store = context.get("redis.store")
        settings = SettingsStore(context.get("mysql.store"), store.prefix)
        values = await settings.load("site")
        groups = {name: dict(value) for name, value in self.groups.items()}
        for name, value in values.items():
            if name in groups:
                groups[name].update(site_policy(value, {
                    k: v for k, v in groups[name].items() if k in site_policy({})}))
        self.download_settings = context.get("download.settings")
        resources = dict(self.download_settings.saved)
        self.service = HttpService(store.client, store.prefix, groups,
            records=context.get("collection.records"), settings=settings, pool=context.get("proxy.pool"),
            resources={**resources, **self.local_options})
        self.download_settings.activate(resources)
        return {"http.fetch": self.service}

    async def stop(self) -> None:
        if self.service:
            await self.service.close()
            self.service = None
        if self.download_settings:
            self.download_settings.deactivate()
            self.download_settings = None

    def health(self) -> dict:
        return {"groups": {name: self.service.activity_snapshot(name) for name in self.service.stats}
                          if self.service else {},
                "global_active_requests": self.service.global_active if self.service else 0,
                "global_concurrency_limit": self.service.global_limit if self.service else 0,
                "buffer": self.service.buffer_budget.health() if self.service else {}}
