import asyncio
import json
import time
from dataclasses import replace

import httpx
import pytest
from test_proxy_pool import Directory, directory_entry
from test_sina_universe import Source, collector, row

from empire.contracts.download import STOCK_RESPONSE
from empire.plugins.infra.capacity import capacity
from empire.plugins.infra.http import HttpService, RateGroup
from empire.plugins.infra.proxy_pool import ProxyPool
from empire.plugins.infra.routing import USE_PROXY, site_policy


async def routed_request_and_close(service):
    response = await service.request("GET", "https://sina.com.cn/", allowed_domains=("sina.com.cn",))
    response.close()


@pytest.mark.parametrize("count,slots,interval", [(0, 1, 2000), (2, 2, 1000),
                                                (20, 20, 100), (50, 50, 40), (100, 64, 32)])
def test_automatic_capacity_grows_with_distinct_exit_ips(count, slots, interval):
    group = RateGroup("sina", ("sina.com.cn",), max_concurrency=64, scaling_mode="auto")
    limits = capacity(group, count)
    assert limits["effective_concurrency"] == slots
    assert limits["effective_interval_ms"] == interval
    fixed = capacity(replace(group, scaling_mode="fixed", max_concurrency=1), count)
    assert fixed["effective_concurrency"] == 1 and fixed["effective_interval_ms"] == 500


@pytest.mark.parametrize("values", [{"max_concurrency": 1025}, {"max_rps": -1},
                                   {"max_rps": True}, {"scaling_mode": "unknown"}])
def test_invalid_scaling_policy_is_rejected(values):
    with pytest.raises(ValueError):
        site_policy(values)


def test_optional_website_ceiling_can_limit_exit_ip_scaling():
    group = RateGroup("sina", ("sina.com.cn",), max_concurrency=64,
                      scaling_mode="auto", max_rps=20)
    assert capacity(group, 50)["effective_interval_ms"] == 50
    assert capacity(group, 50)["rate_ceiling_rps"] == 20


class ParallelSource(Source):
    def __init__(self, *, broken=None):
        super().__init__({n: [row(f"sz{100000 - n:06}")] for n in range(1, 71)}, count=70)
        self.active = self.peak = 0
        self.completed = []
        self.broken = broken

    async def parallelism(self, *args):
        return 20

    async def request(self, method, url, *, params, **kwargs):
        page = params.get("page")
        if page is None or page == 71:
            return await super().request(method, url, params=params, **kwargs)
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            await asyncio.sleep(.025 if page % 20 == 1 else .001)
            self.completed.append(page)
            if page == self.broken:
                return httpx.Response(200, content=f"invalid-page-{page}".encode())
            return await super().request(method, url, params=params, **kwargs)
        finally:
            self.active -= 1


async def test_seventy_pages_download_concurrently_but_publish_in_order():
    source = ParallelSource()
    item = collector(source)
    item.page_size = 1
    result = await item._collect()
    assert result["pages"] == result["collected"] == 70
    assert 2 <= source.peak <= 20 and source.active == 0
    assert source.completed[0] != 1
    pages = [e.raw_payload["page"] for e in item.ingest.events if e.dataset.endswith("page")]
    assert pages == list(range(1, 71))
    assert item.ingest.state["cursor"]["phase"] == "complete"


async def test_prefetch_uses_configured_policy_for_both_reservation_and_download():
    configured = replace(STOCK_RESPONSE, max_body_bytes=256 * 1024, max_wire_bytes=256 * 1024)

    class ConfiguredSource(ParallelSource):
        def response_policy(self, profile):
            assert profile == "stocks"
            return configured

        async def request(self, method, url, *, params, **kwargs):
            assert kwargs["policy"] is configured
            if kwargs.get("reservation") is not None:
                assert kwargs["reservation"].size == configured.reservation_bytes
            return await super().request(method, url, params=params, **kwargs)

    source = ConfiguredSource()
    item = collector(source)
    item.page_size = 1
    await item._collect()
    assert source.buffer_budget.peak == 20 * configured.reservation_bytes
    assert source.buffer_budget.used == 0


async def test_failed_out_of_order_page_keeps_exact_checkpoint_and_diagnostic_for_resume():
    source = ParallelSource(broken=3)
    item = collector(source)
    item.page_size = 1
    with pytest.raises(ValueError):
        await item._collect()
    assert source.active == 0
    assert item.ingest.state["cursor"]["next_page"] == 3
    assert not any(e.dataset.endswith("complete") for e in item.ingest.events)
    assert item.records.errors[0]["raw_body"] == b"invalid-page-3"
    assert item.records.errors[0]["metadata"]["params"]["page"] == 3
    resumed = collector(ParallelSource(), item.ingest)
    resumed.page_size = 1
    await resumed._collect()
    pages = [e.raw_payload["page"] for e in item.ingest.events if e.dataset.endswith("page")]
    assert pages == list(range(1, 71))


async def test_cancel_drains_all_speculative_requests_without_advancing_checkpoint():
    class Blocked(ParallelSource):
        async def request(self, method, url, *, params, **kwargs):
            if "page" not in params:
                return await super().request(method, url, params=params, **kwargs)
            self.active += 1
            try:
                await asyncio.Event().wait()
            finally:
                self.active -= 1

    source = Blocked()
    item = collector(source)
    item.page_size = 1
    task = asyncio.create_task(item._collect())
    expected_active = min(20, source.buffer_budget.limit // STOCK_RESPONSE.reservation_bytes)
    async with asyncio.timeout(1):
        while source.active != expected_active:
            await asyncio.sleep(.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert source.active == 0 and not item.records.errors
    assert item.ingest.state["cursor"]["next_page"] == 1


async def test_fifty_device_routing_is_concurrent_bounded_and_tracks_removal():
    directory = Directory()
    now = time.monotonic()
    directory.mapping = {f"node{i:03}": directory_entry(
        f"node{i:03}", f"socks5h://u:p@localhost:{31000+i}", f"203.0.113.{i+1}") for i in range(50)}
    directory.expires = {raw: now + 180 for raw in directory.mapping.values()}
    active, peak, used = 0, 0, set()

    def factory(url):
        async def response(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            used.add(url)
            try:
                await asyncio.sleep(.03)
                return httpx.Response(200)
            finally:
                active -= 1
        return httpx.AsyncClient(transport=httpx.MockTransport(response))

    pool = ProxyPool(directory, client_factory=factory)
    service = HttpService(directory, "test", {"sina": {"domains": ["sina.com.cn"],
        "scaling_mode": "auto", "max_concurrency": 64, "max_rps": 100,
        "proxy_interval_ms": 100}}, pool=pool)
    token = USE_PROXY.set(True)
    try:
        assert await service.parallelism("https://sina.com.cn/", ("sina.com.cn",)) == 50
        await asyncio.gather(*(routed_request_and_close(service) for _ in range(50)))
        assert service.buffer_budget.used == 0 and not service.responses
        assert 1 < peak <= 50 and active == 0 and len(used) >= 10
        assert all(b[1] - a[1] >= 9 for a, b in zip(directory.permits, directory.permits[1:]))
        directory.mapping = dict(list(directory.mapping.items())[:2])
        await pool.refresh()
        assert await service.parallelism("https://sina.com.cn/", ("sina.com.cn",)) == 2
        assert all(not e.busy for e in pool.entries.values())
    finally:
        USE_PROXY.reset(token)
        await service.close()
        await pool.close()


async def test_same_exit_ip_shares_site_rate_and_concurrency_across_devices():
    directory = Directory()
    now = time.monotonic()
    values = {
        code: json.dumps({"code": code, "proxy": f"socks5h://u:p@localhost:{port}",
                          "exit_ip": "223.73.162.16"})
        for code, port in (("node001", 31001), ("node002", 31002))
    }
    directory.mapping = values
    directory.expires = {raw: now + 180 for raw in values.values()}
    active = peak = 0

    def factory(url):
        async def response(request):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            try:
                await asyncio.sleep(.01)
                return httpx.Response(200)
            finally:
                active -= 1
        return httpx.AsyncClient(transport=httpx.MockTransport(response))

    pool = ProxyPool(directory, client_factory=factory)
    service = HttpService(directory, "test", {"sina": {"domains": ["sina.com.cn"],
        "scaling_mode": "auto", "max_concurrency": 64, "max_rps": 0,
        "proxy_interval_ms": 100}}, pool=pool)
    token = USE_PROXY.set(True)
    try:
        assert await service.parallelism("https://sina.com.cn/", ("sina.com.cn",)) == 1
        await asyncio.gather(*(routed_request_and_close(service) for _ in range(2)))
        assert service.buffer_budget.used == 0 and not service.responses
        assert peak == 1 and active == 0
        assert len({permit[0] for permit in directory.permits}) == 1
        assert directory.permits[1][1] - directory.permits[0][1] >= 99
    finally:
        USE_PROXY.reset(token)
        await service.close()
        await pool.close()


async def test_empty_pool_fallback_serializes_local_requests_even_with_large_ceiling():
    directory = Directory()
    directory.mapping.clear()
    active = peak = 0

    async def respond(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(.01)
            return httpx.Response(200)
        finally:
            active -= 1

    pool = ProxyPool(directory)
    service = HttpService(directory, "test", {"sina": {"domains": ["sina.com.cn"],
        "scaling_mode": "auto", "max_concurrency": 64, "max_rps": 100,
        "proxy_interval_ms": 100, "min_interval_ms": 100}},
        pool=pool, transport=httpx.MockTransport(respond))
    token = USE_PROXY.set(True)
    try:
        await asyncio.gather(*(routed_request_and_close(service) for _ in range(4)))
        assert service.buffer_budget.used == 0 and not service.responses
        assert peak == 1 and active == 0
        assert service.stats["sina"]["fallback_requests"] == 4
        assert all(b[1] - a[1] >= 99 for a, b in zip(directory.permits, directory.permits[1:]))
        assert service.direct_active["sina"] == 0
    finally:
        USE_PROXY.reset(token)
        await service.close()
        await pool.close()


async def test_parallel_duplicate_boundary_prevents_completion():
    source = ParallelSource()
    source.pages[3] = source.pages[2]
    item = collector(source)
    item.page_size = 1
    with pytest.raises(ValueError, match="排序边界"):
        await item._collect()
    assert item.ingest.state["cursor"]["next_page"] == 3
    assert not any(e.dataset.endswith("complete") for e in item.ingest.events)
    assert source.active == 0
