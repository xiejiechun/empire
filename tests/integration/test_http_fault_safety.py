"""Real Redis cooldowns; isolated keys and mock HTTP, never production exits."""
import asyncio
import json
import math
import os
from uuid import uuid4

import httpx
import pytest

from empire.core.config import load_config
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.proxy_pool import ProxyPool
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import USE_PROXY

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get("EMPIRE_INTEGRATION") != "1", reason="Explicit integration opt-in required")]


@pytest.mark.parametrize("header,minimum", [
    ("inf", 29), ("NaN", 29), ("1e309", 29), ("-1", 29),
    ("604800", 604799), ("9" * 400, 10**10),
])
@pytest.mark.parametrize("routed", [False, True])
async def test_real_cooldown_blocks_all_exits_and_cancellation_releases_resources(header, minimum, routed):
    client = create_client(load_config()["redis"])
    prefix = "empire:test:" + uuid4().hex
    mapping, directory = prefix + ":mapping", prefix + ":directory"
    calls = []

    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(429, headers={"Retry-After": header})

    transport = httpx.MockTransport(respond)
    pool = ProxyPool(client, mapping_key=mapping, directory_key=directory,
        client_factory=lambda url: httpx.AsyncClient(transport=transport, trust_env=False)) if routed else None
    service = HttpService(client, prefix, {"source": {"domains": ["example.test"],
        "min_interval_ms": 100, "proxy_interval_ms": 100, "scaling_mode": "auto",
        "max_concurrency": 0}}, transport=transport, pool=pool)
    tasks = []
    try:
        if pool:
            now = (await client.time())[0]
            entries = {f"node{i}": json.dumps({"code": f"node{i}",
                "proxy": f"http://fixture:secret@localhost:{31001+i}",
                "exit_ip": f"198.18.0.{i+1}"}) for i in range(2)}
            await client.hset(mapping, mapping=entries)
            await client.zadd(directory, {raw: now + 180 for raw in entries.values()})
        token = USE_PROXY.set(routed)
        try:
            with pytest.raises(httpx.HTTPStatusError):
                await service.request("GET", "https://a.example.test/limited",
                    allowed_domains=("example.test",), max_retries=0)
            tasks.append(asyncio.create_task(service.request("GET", "https://b.example.test/wait",
                allowed_domains=("example.test",))))
        finally:
            USE_PROXY.reset(token)
        # A direct request shares the cooldown with both independent proxy IPs.
        tasks.append(asyncio.create_task(service.request("GET", "https://a.example.test/direct",
            allowed_domains=("example.test",))))
        seconds, micros = await client.time()
        deadline = float(await client.hget(prefix + ":rate:source", "cooldown"))
        assert math.isfinite(deadline)
        assert deadline / 1000 - (seconds + micros / 1_000_000) >= minimum
        await asyncio.sleep(.03)
        assert len(calls) == 1
        assert all(not task.done() for task in tasks)
        for task in tasks:
            task.cancel()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)
        assert all(isinstance(result, asyncio.CancelledError) for result in results)
        assert service.buffer_budget.used == service.global_active == 0
        assert not service.inflight and not service.responses
        if pool:
            assert all(not entry.busy and entry.failures == 0 for entry in pool.entries.values())
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close()
        if pool:
            await pool.close()
        keys = [key async for key in client.scan_iter(match=prefix + ":*")]
        if keys:
            await client.delete(*keys)  # Only this test's random namespace.
        await client.aclose()
