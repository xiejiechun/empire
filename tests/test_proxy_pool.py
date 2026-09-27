import asyncio
import json
import time
from dataclasses import replace

import httpx
import pytest

from empire.plugins.infra.http import COOLDOWN_LUA, HttpService
from empire.plugins.infra.proxy_pool import CANDIDATE, DIRECTORY, ProxyPool, parse_endpoint
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_PERMIT, USE_PROXY


def directory_entry(code, proxy, exit_ip="203.0.113.1"):
    return json.dumps({"code": code, "proxy": proxy, "exit_ip": exit_ip})


class Directory:
    def __init__(self):
        self.mapping = {"node001": directory_entry("node001", "socks5h://user:secret@localhost:31001"),
                        "node002": directory_entry("node002", "socks5h://user:secret@localhost:31002", "203.0.113.2")}
        self.expires = {raw: time.monotonic() + 180 for raw in self.mapping.values()}
        self.next, self.cooldowns, self.permits = {}, {}, []
        self.broken = False
        self.full_reads = self.candidate_reads = 0

    async def eval(self, script, count, *args):
        now = time.monotonic() * 1000
        if script == DIRECTORY:
            self.full_reads += 1
            if self.broken:
                raise RuntimeError("credential-containing failure must not propagate")
            result = []
            for code, raw in self.mapping.items():
                remaining = self.expires.get(raw, 0) - time.monotonic()
                if remaining > 0:
                    result.extend([code, raw, str(remaining)])
            return result
        if script == CANDIDATE:
            self.candidate_reads += 1
            if self.broken:
                raise RuntimeError("credential-containing failure must not propagate")
            code = args[-1]
            raw = self.mapping.get(code)
            remaining = self.expires.get(raw, 0) - time.monotonic()
            return [code, raw, str(remaining)] if raw and remaining > 0 else []
        if script == COOLDOWN_LUA:
            key, ms = args
            self.cooldowns[key] = max(self.cooldowns.get(key, 0), now + ms)
            return self.cooldowns[key]
        assert script == ROUTE_PERMIT
        site, total, device, total_ms, device_ms, direct = args
        wait = max(self.cooldowns.get(site, 0), self.next.get(total, 0),
                   self.next.get(device, 0)) - now
        if wait > 0:
            return max(1, int(wait))
        self.next[total], self.next[device] = now + total_ms, now + device_ms
        self.permits.append((device, now))
        return 0


def test_literal_directory_credentials_are_encoded_once_without_leaking_repr():
    raw = directory_entry("node001", "socks5h://u@x:p@ss%2F/密@localhost:31001")
    endpoint = parse_endpoint("node001", raw, 180)
    assert endpoint.url == "socks5h://u%40x:p%40ss%2F%2F%E5%AF%86@localhost:31001"
    assert "p@ss" not in repr(endpoint) and "socks5h" not in repr(endpoint)


def test_json_raw_proxy_is_socks5h_with_literal_credentials():
    raw = directory_entry("node001", "u@x:p@ss%2F/密@localhost:31001")
    endpoint = parse_endpoint("node001", raw, 180)
    assert endpoint.url == "socks5h://u%40x:p%40ss%252F%2F%E5%AF%86@localhost:31001"
    assert endpoint.exit_ip == "203.0.113.1"
    assert "p@ss" not in repr(endpoint)


@pytest.mark.parametrize(("raw", "scheme", "protocol"), [
    ("http://client:secret@localhost:21001", "http://", "HTTP"),
    ("https://client:secret@localhost:21001", "https://", "HTTPS"),
    ("socks5://client:secret@localhost:31001", "socks5://", "SOCKS5"),
    ("socks5h://client:secret@localhost:31001", "socks5h://", "SOCKS5"),
])
def test_complete_proxy_urls_keep_declared_protocol(raw, scheme, protocol):
    endpoint = parse_endpoint("node001", directory_entry("node001", raw), 180)
    assert endpoint.url.startswith(scheme)
    assert endpoint.protocol == protocol
    assert endpoint.proxy_address in {"localhost:21001", "localhost:31001"}
    assert "secret" not in repr(endpoint)


def test_complete_proxy_url_does_not_double_encode_credentials():
    endpoint = parse_endpoint("node001", directory_entry("node001", "http://u%40x:p%2Fword@localhost:21001"), 180)
    assert endpoint.url == "http://u%40x:p%2Fword@localhost:21001"


def test_ipv6_proxy_address_is_unambiguous_and_has_no_credentials():
    endpoint = parse_endpoint("node001", directory_entry("node001", "socks5h://user:secret@[2001:db8::1]:31001"), 180)
    assert endpoint.proxy_address == "[2001:db8::1]:31001"
    assert "user" not in endpoint.proxy_address and "secret" not in endpoint.proxy_address


def test_unknown_proxy_scheme_is_rejected_without_leaking_credentials():
    with pytest.raises(ValueError) as caught:
        parse_endpoint("node001", directory_entry("node001", "ftp://client:do-not-leak@localhost:21001"), 180)
    assert "do-not-leak" not in str(caught.value)


def test_json_directory_uses_declared_exit_ip_without_leaking_proxy():
    raw = json.dumps({"code": "node001", "proxy": "http://user:secret@localhost:21001",
                      "exit_ip": "223.73.162.16"})
    endpoint = parse_endpoint("node001", raw, 180)
    assert endpoint.exit_ip == "223.73.162.16" and endpoint.egress_identity == "223.73.162.16"
    assert endpoint.protocol == "HTTP"
    assert "secret" not in repr(endpoint)


@pytest.mark.parametrize("payload", [
    {"code": "other", "proxy": "u:p@localhost:1", "exit_ip": "223.73.162.16"},
    {"code": "node001", "proxy": "u:p@localhost:1", "exit_ip": "not-an-ip"},
    {"code": "node001", "exit_ip": "223.73.162.16"},
])
def test_json_directory_rejects_inconsistent_metadata(payload):
    with pytest.raises(ValueError):
        parse_endpoint("node001", json.dumps(payload), 180)


async def test_devices_sharing_exit_ip_share_one_concurrent_slot():
    directory = Directory()
    first = json.dumps({"code": "node001", "proxy": "socks5h://u:p@localhost:31001",
                        "exit_ip": "223.73.162.16"})
    second = json.dumps({"code": "node002", "proxy": "socks5h://u:p@localhost:31002",
                         "exit_ip": "223.73.162.16"})
    directory.mapping = {"node001": first, "node002": second}
    directory.expires = {first: time.monotonic() + 180, second: time.monotonic() + 180}
    pool = ProxyPool(directory, client_factory=lambda url: httpx.AsyncClient())
    try:
        entry = await pool.acquire(site="sina")
        waiting = asyncio.create_task(pool.acquire(site="sina"))
        await asyncio.sleep(.02)
        assert not waiting.done() and pool.healthy_egress_count() == 1
        snapshot = await pool.snapshot()
        assert snapshot["online"] == 2 and snapshot["online_egresses"] == 1
        await pool.release(entry)
        other = await asyncio.wait_for(waiting, 1)
        await pool.release(other)
    finally:
        await pool.close()


async def test_expiry_remove_rejoin_rotation_and_active_client_retirement():
    directory = Directory()
    pool = ProxyPool(directory, client_factory=lambda url: httpx.AsyncClient())
    try:
        entry = await pool.acquire()
        old_client = entry.client
        directory.mapping.pop(entry.code)
        await pool.refresh()
        assert entry.code not in pool.entries and not old_client.is_closed
        await pool.release(entry)
        await pool._reap()
        assert old_client.is_closed
        raw = directory_entry(entry.code, "socks5h://new:rotated@localhost:31001", entry.exit_ip)
        directory.mapping[entry.code] = raw
        directory.expires[raw] = time.monotonic() + 180
        await pool.refresh()
        assert pool.entries[entry.code].version != entry.version
        directory.expires[raw] = 0  # Hash still present, ZSET lease expired.
        await pool.refresh()
        assert entry.code not in pool.entries
        snapshot_data = await pool.snapshot()
        snapshot = json.dumps(snapshot_data)
        assert "secret" not in snapshot and "rotated" not in snapshot
        assert all(device["proxy_address"].startswith("localhost:")
                   and "@" not in device["proxy_address"]
                   for device in snapshot_data["devices"])
        directory.broken = True
        await pool.refresh()
        assert not pool.entries and pool.error
        assert await pool.acquire(fallback=True) is None
    finally:
        await pool.close()


def setup(directory, handler, *, direct=None):
    pool = ProxyPool(directory, client_factory=lambda url: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: handler(url, request))))
    groups = {"sina": {"domains": ["sina.com.cn"], "min_interval_ms": 100,
                       "proxy_interval_ms": 100, "total_interval_ms": 10, "max_concurrency": 2}}
    service = HttpService(directory, "test", groups, pool=pool,
        transport=httpx.MockTransport(direct or (lambda request: httpx.Response(200, text="direct"))))
    return pool, service


async def get(service, **kwargs):
    return await service.request("GET", "https://finance.sina.com.cn/",
                                 allowed_domains=("sina.com.cn",), **kwargs)


async def test_rotation_shared_device_rate_and_total_cap():
    directory = Directory()
    routes = []

    def respond(url, request):
        routes.append(url)
        return httpx.Response(200)

    pool, service = setup(directory, respond)
    async def consume():
        response = await get(service)
        response.close()

    token = USE_PROXY.set(True)
    try:
        await asyncio.gather(*(consume() for _ in range(5)))
        assert len(set(routes)) == 2
        permits = directory.permits
        assert all(b[1] - a[1] >= 9 for a, b in zip(permits, permits[1:]))
        for key in {key for key, _ in permits}:
            stamps = [stamp for route, stamp in permits if route == key]
            assert all(b - a >= 99 for a, b in zip(stamps, stamps[1:]))
        assert service.active["sina"] == 0
        assert all(e.busy == 0 for e in pool.entries.values())
    finally:
        USE_PROXY.reset(token)
        await service.close()
        await pool.close()


async def test_failing_proxy_retries_on_direct_without_exposing_secret():
    directory = Directory()
    directory.mapping.pop("node002")

    def fail(url, request):
        raise httpx.ConnectError("SECRET " + url)

    pool, service = setup(directory, fail)
    token = USE_PROXY.set(True)
    try:
        response = await get(service, max_retries=1)
        try:
            assert response.text == "direct"
        finally:
            response.close()
        assert pool.entries["node001"].failures == 1
        assert service.stats["sina"]["fallback_requests"] == 1
        pool.entries["node001"].cooldown = 0
        with pytest.raises(httpx.ConnectError) as caught:
            await get(service, max_retries=0)
        assert "secret" not in str(caught.value).lower()
    finally:
        USE_PROXY.reset(token)
        await service.close()
        await pool.close()


@pytest.mark.parametrize("mode", ["fixed", "auto"])
async def test_429_cools_all_routes_including_direct_and_cancellation_releases_lease(mode):
    directory = Directory()
    pool, service = setup(directory, lambda url, request: httpx.Response(429,
                        headers={"Retry-After": "30"}))
    service.rules.groups = [replace(group, scaling_mode=mode) for group in service.rules.groups]
    token = USE_PROXY.set(True)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await get(service, max_retries=0)
        USE_PROXY.reset(token)
        token = USE_PROXY.set(False)
        task = asyncio.create_task(get(service))
        await asyncio.sleep(.1)
        assert len(directory.permits) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.active["sina"] == 0
    finally:
        USE_PROXY.reset(token)
        await service.close()
        await pool.close()


async def test_empty_pool_strict_mode_waits_and_does_not_make_direct_request():
    directory = Directory()
    directory.mapping.clear()
    pool, service = setup(directory, lambda url, request: httpx.Response(200))
    token = USE_PROXY.set(True)
    fallback = PROXY_FALLBACK.set(False)
    try:
        with pytest.raises(TimeoutError):
            await get(service, total_timeout=.03)
        assert not directory.permits and pool.waiting == 0
    finally:
        USE_PROXY.reset(token)
        PROXY_FALLBACK.reset(fallback)
        await service.close()
        await pool.close()
