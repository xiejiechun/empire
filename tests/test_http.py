import asyncio
import time

import httpx
import pytest

from empire.plugins.infra.http import (
    COOLDOWN_LUA,
    HttpService,
    RateRules,
    retry_after_seconds,
)


class MemoryPermits:
    """A scheduling test double; does not validate production Redis scripts."""
    def __init__(self):
        self.next = {}
        self.cooldown = {}
        self.permits = []

    async def eval(self, script, count, key, milliseconds):
        now = time.monotonic() * 1000
        if script == COOLDOWN_LUA:
            self.cooldown[key] = max(self.cooldown.get(key, 0), now + milliseconds)
            return self.cooldown[key]
        wait = max(self.next.get(key, 0), self.cooldown.get(key, 0)) - now
        if wait > 0:
            return max(1, int(wait))
        self.next[key] = now + milliseconds
        self.permits.append((key, now))
        return 0


def groups(interval=30):
    return {"sina": {"domains": ["sina.com.cn"], "min_interval_ms": interval,
                     "max_concurrency": 1}}


def test_domain_grouping_and_suffix_boundaries():
    rules = RateRules(groups())
    allowed = ("sina.com.cn",)
    assert rules.resolve("https://vip.stock.finance.sina.com.cn/", allowed).name == "sina"
    assert rules.resolve("https://FINANCE.SINA.COM.CN./", allowed).name == "sina"
    for host in ("evilsina.com.cn", "sina.com.cn.example.org"):
        with pytest.raises(ValueError):
            rules.resolve(f"https://{host}", allowed)
    with pytest.raises(ValueError):
        rules.resolve("file:///etc/hosts", allowed)


async def test_different_collectors_share_intervals_and_concurrency():
    starts = []
    active = peak = 0

    async def respond(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        starts.append(time.monotonic())
        await asyncio.sleep(.005)
        active -= 1
        return httpx.Response(200, json={"ok": True})

    service = HttpService(MemoryPermits(), "test", groups(), transport=httpx.MockTransport(respond))
    try:
        await asyncio.gather(*[
            service.request("GET", f"https://{host}/", allowed_domains=("sina.com.cn",))
            for host in ("finance.sina.com.cn", "vip.stock.finance.sina.com.cn", "finance.sina.com.cn")
        ])
        assert peak == 1
        assert all(b - a >= .025 for a, b in zip(starts, starts[1:]))
    finally:
        await service.close()


async def test_redirect_gets_fresh_permit_and_rejects_undeclared_domain():
    permits = MemoryPermits()

    async def respond(request):
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "https://vip.stock.finance.sina.com.cn/end"})
        if request.url.path == "/bad":
            return httpx.Response(302, headers={"Location": "https://example.org/"})
        return httpx.Response(200)

    service = HttpService(permits, "test", groups(1), transport=httpx.MockTransport(respond))
    try:
        await service.request("GET", "https://finance.sina.com.cn/start", allowed_domains=("sina.com.cn",))
        assert len(permits.permits) == 2
        with pytest.raises(ValueError, match="not declared"):
            await service.request("GET", "https://finance.sina.com.cn/bad", allowed_domains=("sina.com.cn",))
    finally:
        await service.close()


async def test_429_applies_to_other_plugin_and_wait_is_cancellable():
    permits = MemoryPermits()
    service = HttpService(permits, "test", groups(1), transport=httpx.MockTransport(
        lambda request: httpx.Response(429, headers={"Retry-After": "30"})
    ))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await service.request("GET", "https://finance.sina.com.cn/", allowed_domains=("sina.com.cn",), max_retries=0)
        task = asyncio.create_task(service.request(
            "GET", "https://vip.stock.finance.sina.com.cn/", allowed_domains=("sina.com.cn",)
        ))
        await asyncio.sleep(.02)
        assert len(permits.permits) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        await service.close()


def test_retry_after_invalid_falls_back():
    assert retry_after_seconds("invalid") == 30
    assert retry_after_seconds("5") == 5


class ErrorRecorder:
    def __init__(self):
        self.errors = []

    async def add_error(self, project_id, **fields):
        self.errors.append({"project_id": project_id, **fields})


async def test_retry_keeps_failed_response_even_when_next_attempt_succeeds():
    records = ErrorRecorder()
    responses = [httpx.Response(503, content=b"temporary failure"),
                 httpx.Response(200, content=b"successful response")]
    service = HttpService(MemoryPermits(), "test", groups(1), records=records,
                          transport=httpx.MockTransport(lambda request: responses.pop(0)))
    try:
        result = await service.request("GET", "https://finance.sina.com.cn/",
            allowed_domains=("sina.com.cn",), project_id="sina-news", max_retries=1)
        assert result.status_code == 200
        assert len(records.errors) == 1
        assert records.errors[0]["project_id"] == "sina-news"
        assert records.errors[0]["raw_body"] == b"temporary failure"
        assert records.errors[0]["status_code"] == 503
        assert records.errors[0]["metadata"]["attempt"] == 1
    finally:
        await service.close()


async def test_final_http_failure_is_recorded_once_and_marked_for_collector():
    records = ErrorRecorder()
    service = HttpService(MemoryPermits(), "test", groups(1), records=records,
        transport=httpx.MockTransport(lambda request: httpx.Response(403, content=b"denied")))
    try:
        with pytest.raises(httpx.HTTPStatusError) as caught:
            await service.request("GET", "https://finance.sina.com.cn/",
                allowed_domains=("sina.com.cn",), project_id="sina-stocks", max_retries=0)
        assert caught.value.diagnostic_recorded
        assert len(records.errors) == 1
        assert records.errors[0]["raw_body"] == b"denied"
    finally:
        await service.close()
