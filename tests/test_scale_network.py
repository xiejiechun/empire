"""100–1000 isolated, virtual exits: admission, bounded discovery and cleanup."""
import asyncio
import ssl
import time
from dataclasses import replace
from ipaddress import ip_address
from types import SimpleNamespace

import httpx
import pytest
from test_http import MemoryPermits
from test_prefetch_budget import Response, wait_until
from test_proxy_pool import Directory, directory_entry

from empire.contracts.download import ResponsePolicy
from empire.plugins.collection.prefetch import ordered_prefetch
from empire.plugins.infra.capacity import capacity
from empire.plugins.infra.http import HttpService, RateGroup
from empire.plugins.infra.proxy_pool import CANDIDATE, DIRECTORY, ProxyPool, parse_endpoint
from empire.plugins.infra.request_activity import RequestRate
from empire.plugins.infra.resources import ByteBudget
from empire.plugins.infra.routing import USE_PROXY, site_policy


def directory_with(count, *, shared_ip=False):
    directory = Directory()
    directory.mapping = {f"node{i:04}": directory_entry(f"node{i:04}",
        f"http://u:p@localhost:{31000+i}",
        str(ip_address(int(ip_address("198.18.0.1")) + (0 if shared_ip else i))))
        for i in range(count)}
    directory.expires = {raw: time.monotonic() + 180 for raw in directory.mapping.values()}
    return directory


class Client:
    def __init__(self):
        self.closed = False

    async def aclose(self):
        self.closed = True


@pytest.mark.parametrize("count", [100, 300, 1000])
async def test_large_directory_uses_one_scan_and_constant_size_candidate_checks(count):
    directory = directory_with(count)
    pool = ProxyPool(directory, client_factory=lambda url: Client())
    entries = []
    try:
        entries = await asyncio.gather(*(pool.acquire(site="sina") for _ in range(count)))
        assert len({entry.exit_ip for entry in entries}) == count
        assert directory.full_reads == 1 and directory.candidate_reads == count
        assert sum(entry.busy for entry in pool.entries.values()) == count
        assert pool.healthy_count() == count
        await asyncio.gather(*(pool.release(entry) for entry in entries))
        assert all(not entry.busy for entry in entries)
    finally:
        for entry in entries:
            if entry.busy:
                await pool.release(entry)
        await pool.close()
    assert all(entry.client.closed for entry in entries)


async def test_cached_candidate_is_checked_for_removal_expiry_rotation_and_rejoin():
    directory = directory_with(3)
    pool = ProxyPool(directory, client_factory=lambda url: Client())
    try:
        await pool.refresh()
        directory.mapping.pop("node0000")
        directory.expires[directory.mapping["node0001"]] = 0
        raw = directory_entry("node0002", "socks5h://new:rotated@localhost:31002", "198.18.0.3")
        directory.mapping["node0002"] = raw
        directory.expires[raw] = time.monotonic() + 180
        chosen = await pool.acquire(site="sina")
        assert chosen.code == "node0002" and "rotated" in chosen.url
        assert directory.full_reads == 1  # No full scan per invalid candidate.
        await pool.release(chosen)
        raw = directory_entry("node0000", "http://u:p@localhost:31000", "198.18.0.1")
        directory.mapping["node0000"] = raw
        directory.expires[raw] = time.monotonic() + 180
        pool.refreshed_at -= 2
        await pool.refresh(waiting=True)
        assert pool.healthy_count() == 2
    finally:
        await pool.close()


async def test_candidate_validation_is_reserved_before_await_and_cancel_releases_it():
    directory = directory_with(100, shared_ip=True)
    entered, gate = asyncio.Event(), asyncio.Event()
    evaluate = directory.eval

    async def blocked(script, count, *args):
        if script == CANDIDATE:
            entered.set()
            await gate.wait()
        return await evaluate(script, count, *args)

    directory.eval = blocked
    pool = ProxyPool(directory, client_factory=lambda url: Client())
    first = asyncio.create_task(pool.acquire(site="sina"))
    second = None
    try:
        await entered.wait()
        second = asyncio.create_task(pool.acquire(site="sina"))
        await asyncio.sleep(.01)
        assert sum(entry.busy for entry in pool.entries.values()) == 1
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        gate.set()
        entry = await asyncio.wait_for(second, 2)
        await pool.release(entry)
        assert all(not item.busy for item in pool.entries.values()) and pool.waiting == 0
    finally:
        gate.set()
        for task in (first, second):
            if task and not task.done():
                task.cancel()
        await asyncio.gather(*(task for task in (first, second) if task), return_exceptions=True)
        await pool.close()


async def test_cancelled_retirement_retains_close_task_until_real_close_finishes():
    started, proceed = asyncio.Event(), asyncio.Event()

    class SlowClient(Client):
        async def aclose(self):
            started.set()
            await proceed.wait()
            await super().aclose()

    directory = directory_with(1)
    pool = ProxyPool(directory, client_factory=lambda url: SlowClient())
    entry = await pool.acquire(site="sina")
    directory.mapping.clear()
    await pool.refresh()
    await pool.release(entry)
    release = asyncio.create_task(pool._reap())
    await started.wait()
    release.cancel()
    with pytest.raises(asyncio.CancelledError):
        await release
    assert entry in pool.retired and pool.close_tasks and not entry.client.closed
    close = asyncio.create_task(pool.close())
    await asyncio.sleep(0)
    assert not close.done()
    proceed.set()
    await asyncio.wait_for(close, 2)
    assert entry.client.closed and not pool.retired and not pool.close_tasks


@pytest.mark.parametrize("healthy,global_limit,site_limit,expected", [
    (100, 128, 0, 100), (300, 384, 0, 300), (1000, 1024, 0, 1000),
    (1000, 128, 0, 128), (1000, 1024, 17, 17), (0, 128, 0, 1),
])
def test_one_capacity_contract_applies_global_site_and_distinct_ip_limits(
        healthy, global_limit, site_limit, expected):
    group = RateGroup("sina", ("sina.com.cn",), max_concurrency=site_limit,
                      scaling_mode="auto", proxy_interval_ms=100)
    result = capacity(group, healthy, global_limit)
    assert result["effective_concurrency"] == expected
    assert result["rate_ceiling_rps"] == (expected * 10 if healthy else .5)
    assert site_policy({"max_concurrency": site_limit})["max_concurrency"] == site_limit


def test_rate_counter_remains_bounded_without_clipping_high_request_counts():
    counter = RequestRate()
    for tick in range(100):
        for _ in range(1500):
            counter.add(tick / 10)
    assert len(counter.buckets) == 100 and counter.rate(9.9) == 15000
    counter.add(10)
    assert len(counter.buckets) == 100 and counter.rate(10) == 14850.1
    assert counter.rate(20) == 0 and not counter.buckets


@pytest.mark.parametrize("count,window", [(100, 128), (300, 384), (1000, 1024)])
async def test_http_full_pipeline_scales_to_virtual_exits_without_real_target_traffic(count, window):
    directory = directory_with(count)
    gate, ready = asyncio.Event(), asyncio.Event()
    active = peak = 0
    tls = ssl.create_default_context()

    async def respond(request):
        nonlocal active, peak
        active += 1
        peak = max(active, peak)
        if active == count:
            ready.set()
        try:
            await gate.wait()
            return httpx.Response(200, content=b"{}")
        finally:
            active -= 1

    pool = ProxyPool(directory, client_factory=lambda url: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), verify=tls))
    service = HttpService(directory, "scale-test", {"sina": {"domains": ["sina.test"],
        "scaling_mode": "auto", "max_concurrency": 0, "proxy_interval_ms": 100}},
        pool=pool, resources={"max_parallel_downloads": window})
    token = USE_PROXY.set(True)
    policy = ResponsePolicy(max_body_bytes=16, max_wire_bytes=16)

    async def get():
        response = await service.request("GET", "https://sina.test/",
            allowed_domains=("sina.test",), policy=policy)
        response.close()

    tasks = [asyncio.create_task(get()) for _ in range(count)]
    try:
        await asyncio.wait_for(ready.wait(), 10)
        assert active == peak == service.global_active == count
        assert directory.candidate_reads == count
        assert directory.full_reads <= 3
        gate.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 10)
        assert not service.responses and not service.inflight
        assert service.global_active == active == service.buffer_budget.used == 0
        assert all(not entry.busy for entry in pool.entries.values())
    finally:
        gate.set()
        USE_PROXY.reset(token)
        await service.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.close()


async def test_cross_website_global_cap_and_live_site_lowering_never_leak_permits():
    directory = directory_with(100)
    release, at_capacity = asyncio.Event(), asyncio.Event()
    active, peak, entered = 0, 0, 0
    tls = ssl.create_default_context()

    async def respond(request):
        nonlocal active, peak, entered
        active += 1
        entered += 1
        peak = max(peak, active)
        if active == 7:
            at_capacity.set()
        try:
            await release.wait()
            return httpx.Response(200)
        finally:
            active -= 1

    pool = ProxyPool(directory, client_factory=lambda url: httpx.AsyncClient(
        transport=httpx.MockTransport(respond), verify=tls))
    groups = {name: {"domains": [f"{name}.test"], "scaling_mode": "auto",
                    "max_concurrency": 0, "proxy_interval_ms": 100} for name in ("a", "b")}
    service = HttpService(directory, "test", groups, pool=pool, resources={"max_parallel_downloads": 7})
    token = USE_PROXY.set(True)
    tasks = []

    async def get(name):
        response = await service.request("GET", f"https://{name}.test/", allowed_domains=(f"{name}.test",))
        response.close()

    try:
        tasks = [asyncio.create_task(get("a" if i % 2 else "b")) for i in range(30)]
        await asyncio.wait_for(at_capacity.wait(), 3)
        assert active == service.global_active == peak == 7
        settings = await service.settings()
        assert sum(site.get("waiting_reasons", {}).get("global", 0) for site in settings) > 0
        service.rules.groups = [replace(group, max_concurrency=1) for group in service.rules.groups]
        await asyncio.sleep(.01)
        assert entered == 7  # Existing requests finish; a lower limit does not cancel them.
        release.set()
        await asyncio.wait_for(asyncio.gather(*tasks), 5)
        assert service.global_peak == 7 and service.global_active == 0
        assert all(count == 0 for count in service.active.values())
        assert service.buffer_budget.used == 0 and all(not entry.busy for entry in pool.entries.values())
    finally:
        release.set()
        USE_PROXY.reset(token)
        await service.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.close()


@pytest.mark.parametrize("count", [100, 300, 1000])
async def test_large_ordered_prefetch_uses_configured_window_and_reports_real_budget(count):
    budget = ByteBudget(count * 10)
    gate = asyncio.Event()
    starts, published, states = [], [], []

    async def width():
        return count

    async def fetch(number, lease):
        starts.append(number)
        if number == 1:
            await gate.wait()
        return Response(number, lease)

    async def consume():
        async with ordered_prefetch(1, count + 1, fetch, width, budget=budget,
                                    reservation_bytes=10, on_state=states.append) as reads:
            async for page, response in reads:
                published.append(page)

    task = asyncio.create_task(consume())
    try:
        await wait_until(lambda: len(starts) == count and states[-1]["download_ready_pages"] == count - 1)
        assert not published and budget.used == count * 10
        assert states[-1]["download_pending_pages"] == count
        gate.set()
        await asyncio.wait_for(task, 5)
        assert published == list(range(1, count + 2))
        assert budget.used == 0 and states[-1]["download_pending_pages"] == 0
        assert states[-1]["download_wait_reason"] == "idle"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_budget_blocked_prefetch_is_visible_even_when_not_inside_reserve_wait():
    budget = ByteBudget(20)
    gate = asyncio.Event()
    states = []

    async def width():
        return 128

    async def fetch(page, lease):
        await gate.wait()
        return Response(page, lease)

    async def consume():
        async with ordered_prefetch(1, 5, fetch, width, budget=budget,
                                    reservation_bytes=10, on_state=states.append) as reads:
            async for _ in reads:
                pass

    task = asyncio.create_task(consume())
    try:
        await wait_until(lambda: states and states[-1]["download_pending_pages"] == 2)
        assert states[-1]["download_wait_reason"] == "network" and budget.waiting == 0
        assert states[-1]["download_buffer_limited"]
        assert states[-1]["download_concurrency"] == 2
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert budget.used == 0


async def test_repeated_cancellation_waits_for_prefetch_cleanup_before_releasing_buffers():
    budget = ByteBudget(1000)
    cleanup_started, cleanup_gate = asyncio.Event(), asyncio.Event()

    async def width():
        return 100

    async def fetch(page, lease):
        try:
            await asyncio.Event().wait()
        finally:
            cleanup_started.set()
            await cleanup_gate.wait()

    async def consume():
        async with ordered_prefetch(1, 100, fetch, width, budget=budget, reservation_bytes=10) as reads:
            async for _ in reads:
                pass

    task = asyncio.create_task(consume())
    await wait_until(lambda: budget.used == 1000)
    task.cancel()
    await cleanup_started.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done() and budget.used == 1000
    cleanup_gate.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert budget.used == 0


async def test_concurrent_reapers_remove_owned_entries_idempotently():
    started, gate = asyncio.Event(), asyncio.Event()

    class SlowClient(Client):
        async def aclose(self):
            started.set()
            await gate.wait()
            await super().aclose()

    pool = ProxyPool(Directory())
    first = parse_endpoint("a", directory_entry("a", "http://u:p@localhost:31001"), 180)
    second = parse_endpoint("b", directory_entry("b", "http://u:p@localhost:31002"), 180)
    first.client = SlowClient()
    pool.retired = [first, second]
    tasks = [asyncio.create_task(pool._reap()) for _ in range(2)]
    await started.wait()
    gate.set()
    await asyncio.gather(*tasks)
    assert not pool.retired and not pool.close_tasks and first.client.closed
    await pool.close()


async def test_close_during_directory_read_cannot_repopulate_closed_pool():
    directory = directory_with(100)
    started, gate = asyncio.Event(), asyncio.Event()
    evaluate = directory.eval

    async def blocked(script, count, *args):
        if script == DIRECTORY:
            started.set()
            await gate.wait()
        return await evaluate(script, count, *args)

    directory.eval = blocked
    pool = ProxyPool(directory)
    refresh = asyncio.create_task(pool.refresh())
    await started.wait()
    await pool.close()
    gate.set()
    await refresh
    assert pool.closed and not pool.entries and not pool.retired
    with pytest.raises(RuntimeError, match="停止"):
        await pool.acquire(fallback=True)


async def test_slow_retired_close_does_not_hold_discovery_or_new_assignments():
    started, gate = asyncio.Event(), asyncio.Event()

    class SlowClient(Client):
        async def aclose(self):
            started.set()
            await gate.wait()
            await super().aclose()

    directory = directory_with(2)
    pool = ProxyPool(directory, client_factory=lambda url: SlowClient())
    first = await pool.acquire()
    directory.mapping.pop(first.code)
    await pool.release(first)
    await pool.refresh()
    await started.wait()
    second = await asyncio.wait_for(pool.acquire(), .2)
    assert second.code != first.code and not first.client.closed
    await pool.release(second)
    gate.set()
    await pool.close()
    assert not pool.close_tasks


async def test_default_factory_shares_one_verified_tls_context(monkeypatch):
    calls = []

    def client(**kwargs):
        calls.append(kwargs)
        return Client()

    monkeypatch.setattr(httpx, "AsyncClient", client)
    pool = ProxyPool(Directory())
    assert pool.ssl_context is None
    first = pool.factory("http://u:p@localhost:1")
    second = pool.factory("socks5h://u:p@localhost:2")
    assert calls[0]["verify"] is calls[1]["verify"] is pool.ssl_context
    assert pool.ssl_context.verify_mode == ssl.CERT_REQUIRED and pool.ssl_context.check_hostname
    assert all(call["trust_env"] is False for call in calls)
    await first.aclose()
    await second.aclose()
    await pool.close()


@pytest.mark.parametrize("value", [0, -1, 1025, True, 3.5, "128"])
def test_direct_service_rejects_invalid_global_limit(value):
    with pytest.raises(ValueError, match="全局最多同时下载"):
        HttpService(MemoryPermits(), "test", {}, resources={"max_parallel_downloads": value})


async def test_direct_without_pool_reports_actual_active_global_and_site_counts():
    entered, gate = asyncio.Event(), asyncio.Event()

    async def response(request):
        entered.set()
        await gate.wait()
        return httpx.Response(200)

    service = HttpService(MemoryPermits(), "test", {"sina": {"domains": ["sina.test"]}},
        transport=httpx.MockTransport(response))
    task = asyncio.create_task(service.request("GET", "https://sina.test", allowed_domains=("sina.test",)))
    try:
        await entered.wait()
        setting = (await service.settings())[0]
        assert setting["active_requests"] == setting["global_active_requests"] == 1
        gate.set()
        result = await task
        result.close()
        setting = (await service.settings())[0]
        assert setting["active_requests"] == setting["global_active_requests"] == 0
    finally:
        gate.set()
        await service.close()
        await asyncio.gather(task, return_exceptions=True)


async def test_prefetch_distinguishes_network_ordered_and_failed_pages():
    budget = ByteBudget(30)
    finish_later = asyncio.Event()
    states = []

    async def width():
        return 3

    async def fetch(page, lease):
        if page == 1:
            await asyncio.Event().wait()
        await finish_later.wait()
        return SimpleNamespace(error=ValueError("failed page") if page == 2 else None,
                               close=lambda: None)

    async def consume():
        async with ordered_prefetch(1, 3, fetch, width, budget=budget,
                                    reservation_bytes=10, on_state=states.append) as reads:
            async for _ in reads:
                pytest.fail("Later pages cannot cross the first page")

    task = asyncio.create_task(consume())
    try:
        await wait_until(lambda: states and states[-1]["download_pending_pages"] == 3)
        assert states[-1]["download_wait_reason"] == "network"
        assert states[-1]["download_ready_pages"] == states[-1]["download_failed_pages"] == 0
        finish_later.set()
        await wait_until(lambda: states[-1]["download_ready_pages"] == 1)
        assert states[-1]["download_wait_reason"] == "ordered"
        assert states[-1]["download_failed_pages"] == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert budget.used == 0
