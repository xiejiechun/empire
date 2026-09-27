"""Actual Redis scripts, isolated keys and fake outbound HTTP (no target traffic)."""
import json
import os
from time import monotonic
from uuid import uuid4

import httpx
import pytest

from empire.core.config import load_config
from empire.plugins.infra.http import COOLDOWN_LUA, HttpService
from empire.plugins.infra.proxy_pool import CANDIDATE, ProxyPool
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import ROUTE_PERMIT, USE_PROXY


def directory_entry(code, proxy, exit_ip="203.0.113.1"):
    return json.dumps({"code": code, "proxy": proxy, "exit_ip": exit_ip})


pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Explicit integration opt-in required")]


async def test_real_redis_candidate_verifies_current_raw_mapping_and_exact_producer_lease():
    client = create_client(load_config()["redis"])
    prefix = "empire:test:" + uuid4().hex
    mapping, directory = prefix + ":mapping", prefix + ":directory"
    try:
        seconds, micros = await client.time()
        now = seconds + micros / 1000000
        raw = directory_entry("node001", "http://u:p@localhost:31001")
        await client.hset(mapping, "node001", raw)
        await client.zadd(directory, {raw: now + 60})
        value = await client.eval(CANDIDATE, 2, mapping, directory, "node001")
        assert value[:2] == ["node001", raw] and 0 < float(value[2]) <= 60
        newer = directory_entry("node001", "socks5h://u:new@localhost:31001")
        await client.hset(mapping, "node001", newer)
        assert await client.eval(CANDIDATE, 2, mapping, directory, "node001") == []
        await client.zadd(directory, {newer: now + 60})
        assert (await client.eval(CANDIDATE, 2, mapping, directory, "node001"))[1] == newer
        await client.zadd(directory, {newer: now - 1})
        assert await client.eval(CANDIDATE, 2, mapping, directory, "node001") == []
        await client.hdel(mapping, "node001")
        assert await client.eval(CANDIDATE, 2, mapping, directory, "node001") == []
    finally:
        await client.delete(mapping, directory)
        await client.aclose()


async def test_real_redis_directory_expiry_rotation_and_hierarchical_permits():
    client = create_client(load_config()["redis"])
    prefix = "empire:test:" + uuid4().hex
    mapping, directory = prefix + ":mapping", prefix + ":directory"
    site, total, device = prefix + ":site", prefix + ":total", prefix + ":device"
    pool = ProxyPool(client, mapping_key=mapping, directory_key=directory)
    try:
        now = (await client.time())[0]
        await client.hset(mapping, mapping={"node001": directory_entry("node001", "socks5h://u:p@localhost:31001"),
                                          "node002": directory_entry("node002", "socks5h://u:p@localhost:31002", "203.0.113.2")})
        await client.zadd(directory, {directory_entry("node001", "socks5h://u:p@localhost:31001"): now + 180,
                                     directory_entry("node002", "socks5h://u:p@localhost:31002", "203.0.113.2"): now - 1})
        await pool.refresh()
        assert set(pool.entries) == {"node001"}
        version = pool.entries["node001"].version
        await client.hset(mapping, "node001", directory_entry("node001", "socks5h://u:new@localhost:31001"))
        await client.zadd(directory, {directory_entry("node001", "socks5h://u:new@localhost:31001"): now + 180})
        await pool.refresh()
        assert pool.entries["node001"].version != version
        await client.hdel(mapping, "node001")
        await pool.refresh()
        assert not pool.entries  # Unexpired ZSET orphan is not assigned.
        assert await client.eval(ROUTE_PERMIT, 3, site, total, device, 100, 2000, 0) == 0
        assert await client.eval(ROUTE_PERMIT, 3, site, total, device, 100, 2000, 0) > 0
        assert 0 < await client.pttl(device) <= 86400000
        await client.eval(COOLDOWN_LUA, 1, site, 30000)
        assert await client.eval(ROUTE_PERMIT, 3, site, total, site, 100, 100, 1) > 29000
    finally:
        await pool.close()
        await client.delete(mapping, directory, site, total, device)
        await client.aclose()


async def test_real_redis_rotates_devices_under_shared_site_rate():
    client = create_client(load_config()["redis"])
    prefix = "empire:test:" + uuid4().hex
    mapping, directory = prefix + ":mapping", prefix + ":directory"
    calls = []

    def response(request):
        calls.append(monotonic())
        return httpx.Response(200)

    pool = ProxyPool(client, mapping_key=mapping, directory_key=directory,
        client_factory=lambda url: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    service = HttpService(client, prefix, {"sina": {"domains": ["sina.com.cn"],
        "proxy_interval_ms": 100, "total_interval_ms": 50,
        "scaling_mode": "auto", "max_concurrency": 64, "max_rps": 20}}, pool=pool)
    token = USE_PROXY.set(True)
    try:
        now = (await client.time())[0]
        await client.hset(mapping, mapping={"node001": directory_entry("node001", "socks5h://u:p@localhost:31001"),
                                          "node002": directory_entry("node002", "socks5h://u:p@localhost:31002", "203.0.113.2")})
        await client.zadd(directory, {directory_entry("node001", "socks5h://u:p@localhost:31001"): now + 180,
                                     directory_entry("node002", "socks5h://u:p@localhost:31002", "203.0.113.2"): now + 180})
        for _ in range(4):
            downloaded = await service.request("GET", "https://finance.sina.com.cn/",
                                               allowed_domains=("sina.com.cn",))
            downloaded.close()
        assert all(b - a >= .045 for a, b in zip(calls, calls[1:]))
        assert all(e.requests == 2 for e in pool.entries.values())
    finally:
        USE_PROXY.reset(token)
        await service.close()
        await pool.close()
        keys = [key async for key in client.scan_iter(match=prefix + ":*")]
        if keys:
            await client.delete(*keys)  # Only this test's random namespace.
        await client.aclose()
