"""Per-run routing context and atomic site/egress request permits."""
import hashlib
from contextvars import ContextVar

import httpx

from empire.contracts.download_settings import MAX_PARALLEL_DOWNLOADS
from empire.plugins.infra.capacity import capacity
from empire.plugins.infra.request_activity import wait_for_admission

USE_PROXY = ContextVar("empire_use_proxy", default=False)
PROXY_FALLBACK = ContextVar("empire_proxy_fallback", default=True)
ROUTE_COUNTS = ContextVar("empire_route_counts", default=None)

# KEYS: site (including 429 cooldown), total site gate, egress gate.
# ARGV: total interval, egress interval, direct flag. Existing direct next_due is retained.
ROUTE_PERMIT = """
local t = redis.call('TIME')
local now = tonumber(t[1])*1000 + math.floor(tonumber(t[2])/1000)
local cooldown = tonumber(redis.call('HGET', KEYS[1], 'cooldown') or '0')
local total = tonumber(redis.call('GET', KEYS[2]) or '0')
local device = tonumber(redis.call('HGET', KEYS[3], 'next') or '0')
local wait = math.max(cooldown, total, device) - now
if wait > 0 then return math.min(wait, 60000) end
redis.call('SET', KEYS[2], now + tonumber(ARGV[1]), 'PX', math.max(60000,tonumber(ARGV[1])*2))
redis.call('HSET', KEYS[3], 'next', now + tonumber(ARGV[2]))
if ARGV[3] ~= '1' then redis.call('PEXPIRE', KEYS[3], 86400000) end
return 0
"""


def site_policy(value, existing=None):
    merged = {**(existing or {}), **value}
    result = {"min_interval_ms": 2000, "proxy_interval_ms": merged.get("min_interval_ms", 2000),
              "total_interval_ms": min(500, merged.get("min_interval_ms", 2000)),
              "max_concurrency": 1, **merged}
    for name in ("min_interval_ms", "proxy_interval_ms", "total_interval_ms"):
        if type(result[name]) is not int or not 100 <= result[name] <= 60000:
            raise ValueError("网站间隔须为 100～60000 毫秒")
    if type(result["max_concurrency"]) is not int or not 0 <= result["max_concurrency"] <= MAX_PARALLEL_DOWNLOADS:
        raise ValueError(f"网站总并发须为 0～{MAX_PARALLEL_DOWNLOADS}，0 表示跟随全局")
    result.setdefault("scaling_mode", "fixed")
    result.setdefault("max_rps", 0)
    if result["scaling_mode"] not in ("fixed", "auto"):
        raise ValueError("请选择自动扩展或固定限速")
    if type(result["max_rps"]) is not int or not 0 <= result["max_rps"] <= 100:
        raise ValueError("网站每秒请求上限须为 0～100，0 表示不额外限制")
    return {key: result[key] for key in (
        "min_interval_ms", "proxy_interval_ms", "total_interval_ms", "max_concurrency",
        "scaling_mode", "max_rps")}


async def routed_request(service, method, url, allowed, **kwargs):
    """Every attempt/redirect obtains fresh total and egress permits."""
    while True:
        group = service.rules.resolve(url, allowed)
        stats = service.stats.setdefault(group.name, {"requests": 0, "waiting": 0,
                                                       "last_status": None})
        healthy = service.pool.healthy_count() if service.pool is not None else 0
        limits = capacity(group, healthy, service.global_limit)
        if service.global_active >= service.global_limit:
            await wait_for_admission(service, stats, "global")
            continue
        if service.active.get(group.name, 0) >= limits["effective_concurrency"]:
            await wait_for_admission(service, stats, "site")
            continue
        entry = None
        if USE_PROXY.get():
            if service.pool is None:
                if not PROXY_FALLBACK.get():
                    raise RuntimeError("代理池未就绪，且当前任务禁止本机直连")
            else:
                waits = stats.setdefault("waiting_reasons", {})
                waits["egress"] = waits.get("egress", 0) + 1
                try:
                    entry = await service.pool.acquire(fallback=PROXY_FALLBACK.get(), site=group.name)
                finally:
                    waits["egress"] -= 1
        group = service.rules.resolve(url, allowed)
        healthy = service.pool.healthy_count() if service.pool is not None else 0
        limits = capacity(group, healthy, service.global_limit)
        # Pool acquisition can yield while another task consumes the last group slot.
        if (service.global_active >= service.global_limit or
                service.active.get(group.name, 0) >= limits["effective_concurrency"]):
            if entry:
                await service.pool.release(entry)
            reason = "global" if service.global_active >= service.global_limit else "site"
            await wait_for_admission(service, stats, reason)
            continue
        if entry is None and service.direct_active.get(group.name, 0):
            await wait_for_admission(service, stats, "site")
            continue
        service.global_active += 1
        service.global_peak = max(service.global_peak, service.global_active)
        service.active[group.name] = service.active.get(group.name, 0) + 1
        if entry is None:
            service.direct_active[group.name] = service.direct_active.get(group.name, 0) + 1
        try:
            key = f"{service.prefix}:rate:{group.name}"
            route = hashlib.sha256(entry.egress_identity.encode()).hexdigest()[:24] if entry else None
            egress = f"{key}:proxy:{route}" if route else key
            interval = group.proxy_interval_ms if entry else group.min_interval_ms
            delay = int(await service.redis.eval(ROUTE_PERMIT, 3, key, key + ":total", egress,
                                                limits["site_gate_interval_ms"], interval, int(entry is None)))
            if delay > 0 and entry:
                service.pool.defer(entry, group.name, delay)
            if delay <= 0:
                stats["requests"] += 1
                service.recent_requests[group.name].add()
                kind = "proxy_requests" if entry else "direct_requests"
                stats[kind] = stats.get(kind, 0) + 1
                counts = ROUTE_COUNTS.get()
                if counts is not None:
                    counts[kind] = counts.get(kind, 0) + 1
                if USE_PROXY.get() and entry is None:
                    stats["fallback_requests"] = stats.get("fallback_requests", 0) + 1
                    if counts is not None:
                        counts["fallback_requests"] = counts.get("fallback_requests", 0) + 1
                if entry:
                    entry.requests += 1
                try:
                    client = entry.client if entry else service.client
                    response = await service.transfer(client, method, url, key=key, stats=stats, **kwargs)
                except httpx.TransportError as exc:
                    if entry:
                        service.pool.failed(entry)
                        raise httpx.ConnectError(
                            f"代理设备 {entry.code} 请求失败（{type(exc).__name__}），已临时隔离"
                        ) from None
                    raise
                stats["last_status"] = response.status_code
                if entry:
                    if response.status_code == 407:
                        service.pool.failed(entry)
                        response.close()
                        raise httpx.ProxyError(f"代理设备 {entry.code} 认证失败，已临时隔离")
                    entry.failures = 0
                return response
        finally:
            service.global_active -= 1
            service.admission_changed.set()
            service.active[group.name] -= 1
            if entry is None:
                service.direct_active[group.name] -= 1
            if entry:
                await service.pool.release(entry)
        # Re-select on short waits: another device may already have an available permit.
        await wait_for_admission(service, stats, "rate", min(.05, max(.001, delay / 1000)))
