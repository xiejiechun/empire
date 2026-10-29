import asyncio
import time

import httpx
import pytest

from empire.plugins.infra.http import (
    COOLDOWN_LUA,
    HttpService,
    RateRules,
)
from empire.plugins.infra.http_safety import parse_retry_after
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_PERMIT, USE_PROXY


@pytest.mark.parametrize("failure", ["status", "transport", "not_found"])
@pytest.mark.parametrize("recover", [False, True])
async def test_one_hundred_retries_are_bounded_and_can_recover(monkeypatch, failure, recover):
    attempts, delays, deadlines = [], [], []
    original_sleep, original_timeout = asyncio.sleep, asyncio.timeout

    async def fast_sleep(delay):
        delays.append(delay)
        await original_sleep(0)

    def timed(delay):
        deadlines.append(delay)
        return original_timeout(delay)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(asyncio, "timeout", timed)
    records = ErrorRecorder()
    service = HttpService(MemoryPermits(), "test", groups(1), records=records)

    async def one(method, url, allowed, **kwargs):
        attempts.append(len(attempts) + 1)
        if recover and len(attempts) == 101:
            return httpx.Response(200, request=httpx.Request(method, url))
        if failure == "transport":
            raise httpx.ConnectError("temporary network failure")
        return httpx.Response(404 if failure == "not_found" else 502, request=httpx.Request(method, url))

    monkeypatch.setattr(service, "_one", one)
    try:
        options = dict(allowed_domains=("sina.com.cn",), max_retries=100, project_id="sina-news")
        if failure == "not_found":
            options["retry_not_found"] = True
        if recover:
            response = await service._request("GET", "https://finance.sina.com.cn/", **options)
            assert response.status_code == 200
            response.close()
        else:
            with pytest.raises(httpx.ConnectError if failure == "transport" else httpx.HTTPStatusError):
                await service._request("GET", "https://finance.sina.com.cn/", **options)
        assert len(attempts) == 101
        assert delays == [1, 2, 4, 8, 16] + [30] * 95
        assert deadlines[0] == 6000
        assert len(records.errors) == (100 if recover else 101)
        assert service.buffer_budget.used == 0
    finally:
        await service.close()


class MemoryPermits:
    """A scheduling test double; does not validate production Redis scripts."""
    def __init__(self):
        self.next = {}
        self.cooldown = {}
        self.permits = []

    async def eval(self, script, count, *args):
        now = time.monotonic() * 1000
        if script == COOLDOWN_LUA:
            key, milliseconds = args
            self.cooldown[key] = max(self.cooldown.get(key, 0), now + milliseconds)
            return self.cooldown[key]
        assert script == ROUTE_PERMIT
        site, total, device, total_ms, device_ms, _direct = args
        wait = max(self.next.get(total, 0), self.next.get(device, 0),
                   self.cooldown.get(site, 0)) - now
        if wait > 0:
            return max(1, int(wait))
        self.next[total] = now + total_ms
        self.next[device] = now + device_ms
        self.permits.append((device, now))
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
    permits = MemoryPermits()
    active = peak = 0

    async def respond(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(.005)
        active -= 1
        return httpx.Response(200, json={"ok": True})

    service = HttpService(permits, "test", groups(), transport=httpx.MockTransport(respond))
    async def consume(host):
        response = await service.request("GET", f"https://{host}/", allowed_domains=("sina.com.cn",))
        response.close()

    try:
        await asyncio.gather(*[
            consume(host)
            for host in ("finance.sina.com.cn", "vip.stock.finance.sina.com.cn", "finance.sina.com.cn")
        ])
        assert peak == 1
        # The contract spaces permits. First-use client overhead can delay a mock
        # callback after its permit, especially under Windows timer granularity.
        assert len(permits.permits) == 3
        assert all(b[1] - a[1] >= 30 for a, b in zip(permits.permits, permits.permits[1:]))
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
        response = await service.request("GET", "https://finance.sina.com.cn/start", allowed_domains=("sina.com.cn",))
        response.close()
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


async def test_proxy_only_request_never_uses_direct_route_when_pool_is_unavailable():
    service = HttpService(MemoryPermits(), "test", groups(1),
        transport=httpx.MockTransport(lambda request: httpx.Response(200)))
    proxy_token = USE_PROXY.set(True)
    fallback_token = PROXY_FALLBACK.set(False)
    try:
        with pytest.raises(RuntimeError, match="禁止本机直连"):
            await service.request("GET", "https://finance.sina.com.cn/",
                allowed_domains=("sina.com.cn",))
        assert service.stats["sina"]["requests"] == 0
    finally:
        PROXY_FALLBACK.reset(fallback_token)
        USE_PROXY.reset(proxy_token)
        await service.close()


def test_retry_after_invalid_falls_back():
    assert parse_retry_after("invalid").milliseconds == 30000
    assert parse_retry_after("5").milliseconds == 5000


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
        try:
            assert result.status_code == 200
        finally:
            result.close()
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


@pytest.mark.parametrize('enabled,recover,expected', [(False, False, 1), (True, True, 2), (True, False, 3)])
async def test_empty_200_retry_is_opt_in_and_shares_budget(monkeypatch, enabled, recover, expected):
    from empire.plugins.infra.response_reader import DownloadIncompleteError
    service = HttpService(MemoryPermits(), 'test', groups(1), records=ErrorRecorder())
    responses = []
    async def one(method, url, domains, **kwargs):
        response = httpx.Response(200, request=httpx.Request(method, url),
            content=b'ok' if recover and responses else b'')
        responses.append(response)
        return response
    async def sleep(delay):
        pass
    monkeypatch.setattr(service, '_one', one)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    try:
        options = dict(allowed_domains=('sina.com.cn',), project_id='sina-news',
                       max_retries=2, retry_empty_body=enabled)
        if enabled and not recover:
            with pytest.raises(DownloadIncompleteError):
                await service._request('GET', 'https://sina.com.cn/', **options)
        else:
            response = await service._request('GET', 'https://sina.com.cn/', **options)
            assert response.content == (b'ok' if recover else b'')
            response.close()
        assert len(responses) == expected
        assert all(r.is_closed for r in responses)
    finally:
        await service.close()


@pytest.mark.parametrize('sequence,budget,attempts', [
    ([200], 2, 1), ([200, 200], 2, 2), ([503, 200, 200], 2, 3),
    ([503, 200, 200], 1, 2), ([200, 200, 200, 200], 2, 3),
])
async def test_source_retry_shares_transport_budget_and_closes(monkeypatch, sequence, budget, attempts):
    from empire.features.yuanhang_limits.source import transient_reason_failure
    service = HttpService(MemoryPermits(), 'test', groups(1), records=ErrorRecorder())
    responses = []
    async def one(method, url, domains, **kwargs):
        index = len(responses)
        body = {'status_code': 0, 'data': {}} if index == len(sequence)-1 else {
            'status_code': -1, 'status_msg': 'fail',
            'data': {'reasonrevealedList': None, 'reasonKindList': []}}
        response = httpx.Response(sequence[index], request=httpx.Request(method,url), json=body)
        responses.append(response)
        return response
    async def sleep(delay):
        pass
    monkeypatch.setattr(service, '_one', one)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    try:
        result = await service._request('GET', 'https://sina.com.cn/',
            allowed_domains=('sina.com.cn',), project_id='test', max_retries=budget,
            retry_response=transient_reason_failure)
        assert len(responses) == attempts
        assert result.json()['status_code'] == (0 if attempts == len(sequence) else -1)
        result.close()
        assert all(r.is_closed for r in responses)
    finally:
        await service.close()
