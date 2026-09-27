"""Adversarial response metadata across the shared memory/file request path."""
import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from test_download_resources import RawStream
from test_http import MemoryPermits, groups
from test_proxy_pool import Directory

from empire.plugins.infra.http import HttpService
from empire.plugins.infra.http_safety import MAX_COOLDOWN_MS, origin, parse_retry_after
from empire.plugins.infra.proxy_pool import ProxyPool
from empire.plugins.infra.routing import USE_PROXY


@pytest.mark.parametrize("value", [None, "", "oops", "NaN", "inf", "-inf", "1e309",
                                   "1e308", "-1", "+2", "1.5", "1,2", "１２"])
def test_malformed_retry_after_uses_fallback(value):
    result = parse_retry_after(value)
    assert result.milliseconds == 30000 and not result.saturated


@pytest.mark.parametrize("value,expected", [("0", 0), (" 5 ", 5000),
    ("00000005", 5000), ("604800", 604800000), ("31536000", 31536000000)])
def test_standard_retry_after_preserves_long_cooldown(value, expected):
    result = parse_retry_after(value)
    assert result.milliseconds == expected and not result.invalid and not result.saturated


@pytest.mark.parametrize("value", ["9" * 400, "9" * 5000, str(MAX_COOLDOWN_MS)])
def test_astronomic_valid_delay_fails_closed_without_integer_or_float_overflow(value):
    result = parse_retry_after(value)
    assert result.milliseconds == MAX_COOLDOWN_MS and result.saturated and not result.invalid


def test_http_date_keeps_years_of_cooldown_and_accepts_expired_date():
    date = datetime.now(UTC).replace(microsecond=0) + timedelta(days=730)
    result = parse_retry_after(format_datetime(date, usegmt=True))
    assert 730 * 86400000 - 2000 <= result.milliseconds <= 730 * 86400000
    assert parse_retry_after("Fri, 01 Jan 2021 00:00:00 GMT").milliseconds == 0
    assert parse_retry_after("Fri, 31 Dec 9999 23:59:59 GMT").milliseconds > 200000000000000


def test_invalid_origin_does_not_quote_untrusted_port():
    with pytest.raises(ValueError, match="地址无效") as caught:
        origin("https://a.sina.com.cn:do-not-leak/end")
    assert "do-not-leak" not in str(caught.value)


def make_service(tmp_path, handler, *, routed):
    redis = Directory() if routed else MemoryPermits()
    pool = ProxyPool(redis, client_factory=lambda url: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False,
        auth=("default-user", "default-secret"),
        headers={"Cookie": "default=secret", "Authorization": "Bearer default-secret",
                 "Proxy-Authorization": "Bearer proxy-secret", "Host": "wrong.example.test"},
    )) if routed else None
    service = HttpService(redis, "test", groups(1), pool=pool,
        transport=httpx.MockTransport(handler), resources={
            "download_directory": tmp_path / "downloads", "disk_free_margin_bytes": 0})
    service.client.auth = ("default-user", "default-secret")
    service.client.headers.update({"Cookie": "default=secret", "Authorization": "Bearer default-secret",
        "Proxy-Authorization": "Bearer proxy-secret", "Host": "wrong.example.test"})
    return service


async def close_service(service):
    await service.close()
    if service.pool:
        await service.pool.close()


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("file_mode", [False, True])
@pytest.mark.parametrize("target", ["https://b.sina.com.cn/end", "https://a.sina.com.cn:444/end",
                                    "https://a.sina.com.cn:0/end", "https://a.sina.com.cn./end",
                                    "https://a.sina.com.cn/end"])
async def test_cross_origin_strips_every_credential_source(tmp_path, routed, file_mode, target):
    # The third case crosses scheme on the same host (HTTP -> HTTPS), so cookies
    # and explicit auth must also be removed on this seemingly harmless upgrade.
    start = "http://a.sina.com.cn/start" if target == "https://a.sina.com.cn/end" else "https://a.sina.com.cn/start"
    requests, streams = [], []

    def handler(request):
        requests.append(request)
        stream = RawStream([b"%PDF-ok"])
        streams.append(stream)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": target,
                "Set-Cookie": "source=secret; Domain=.sina.com.cn; Path=/"}, stream=stream)
        return httpx.Response(200, stream=stream)

    service = make_service(tmp_path, handler, routed=routed)
    token = USE_PROXY.set(routed)
    try:
        policy = service.file_policy(filename="report.pdf", signature=b"%PDF-") if file_mode else None
        response = await service.request("GET", start, allowed_domains=("sina.com.cn",), policy=policy,
            auth=("explicit-user", "explicit-secret"), cookies={"explicit": "cookie-secret"},
            headers={"Cookie": "explicit=secret", "Authorization": "Bearer explicit-secret",
                     "Proxy-Authorization": "Bearer proxy-secret", "Host": "wrong.example.test"})
        response.close()
        assert len(requests) == 2
        assert "authorization" in requests[0].headers and "cookie" in requests[0].headers
        assert all(name not in requests[1].headers for name in (
            "authorization", "proxy-authorization", "cookie"))
        assert requests[1].headers["host"] == httpx.Request("GET", target).headers["host"]
        assert all(stream.closed for stream in streams)
        assert service.buffer_budget.used == service.global_active == 0
        if file_mode:
            assert (tmp_path / "downloads" / "report.pdf").read_bytes() == b"%PDF-ok"
    finally:
        USE_PROXY.reset(token)
        await close_service(service)


async def test_cross_origin_suppresses_domain_cookie_added_by_previous_response(tmp_path):
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "https://b.sina.com.cn/end",
                "Set-Cookie": "source=secret; Domain=.sina.com.cn; Path=/"})
        return httpx.Response(200)

    service = make_service(tmp_path, handler, routed=False)
    service.client.headers.pop("Cookie")
    try:
        response = await service.request("GET", "https://a.sina.com.cn/start", allowed_domains=("sina.com.cn",))
        response.close()
        assert service.client.cookies.get("source") == "secret"
        assert "cookie" not in seen[-1].headers and "authorization" not in seen[-1].headers
    finally:
        await close_service(service)


@pytest.mark.parametrize("target", ["/end", "https://A.SINA.COM.CN:443/end"])
async def test_same_origin_preserves_explicit_auth_and_cookies(tmp_path, target):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": target}) if request.url.path == "/start" else httpx.Response(200)

    service = make_service(tmp_path, handler, routed=False)
    try:
        response = await service.request("GET", "https://a.sina.com.cn/start", allowed_domains=("sina.com.cn",),
            auth=("explicit-user", "explicit-secret"), headers={"Cookie": "explicit=secret"})
        response.close()
        assert seen[0].headers["authorization"] == seen[1].headers["authorization"]
        assert seen[1].headers["cookie"] == "explicit=secret"
    finally:
        await close_service(service)


async def test_returning_to_original_origin_does_not_restore_credentials(tmp_path):
    seen = []
    targets = {"/start": "https://b.sina.com.cn/back", "/back": "https://a.sina.com.cn/end"}

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": targets[request.url.path]}) if request.url.path in targets else httpx.Response(200)

    service = make_service(tmp_path, handler, routed=False)
    try:
        response = await service.request("GET", "https://a.sina.com.cn/start", allowed_domains=("sina.com.cn",))
        response.close()
        assert all("authorization" not in request.headers and "cookie" not in request.headers for request in seen[1:])
    finally:
        await close_service(service)


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("file_mode", [False, True])
async def test_https_downgrade_rejected_without_target_request_or_resource_leak(tmp_path, routed, file_mode):
    seen, stream = [], RawStream([b"irrelevant"])

    def handler(request):
        seen.append(request)
        return httpx.Response(302, headers={"Location": "http://a.sina.com.cn/end?token=do-not-leak"}, stream=stream)

    service = make_service(tmp_path, handler, routed=routed)
    token = USE_PROXY.set(routed)
    try:
        policy = service.file_policy(filename="report.pdf") if file_mode else None
        with pytest.raises(ValueError, match="HTTPS") as caught:
            await service.request("GET", "https://a.sina.com.cn/start", allowed_domains=("sina.com.cn",), policy=policy)
        assert "do-not-leak" not in str(caught.value) and len(seen) == 1
        assert stream.closed and service.global_active == service.buffer_budget.used == 0
        assert not list((tmp_path / "downloads").glob("*"))
        if service.pool:
            assert all(entry.busy == 0 for entry in service.pool.entries.values())
    finally:
        USE_PROXY.reset(token)
        await close_service(service)


@pytest.mark.parametrize("routed", [False, True])
@pytest.mark.parametrize("file_mode", [False, True])
async def test_cancel_after_redirect_releases_stream_buffer_and_proxy(tmp_path, routed, file_mode):
    streams = [RawStream(), RawStream([b"%PDF-ok"], block_after=0)]
    index = 0

    def handler(request):
        nonlocal index
        stream = streams[index]
        index += 1
        return httpx.Response(302, headers={"Location": "https://b.sina.com.cn/end"}, stream=stream) if index == 1 else httpx.Response(200, stream=stream)

    service = make_service(tmp_path, handler, routed=routed)
    token = USE_PROXY.set(routed)
    try:
        policy = service.file_policy(filename="report.pdf") if file_mode else None
        task = asyncio.create_task(service.request("GET", "https://a.sina.com.cn/start",
            allowed_domains=("sina.com.cn",), policy=policy))
        await asyncio.wait_for(streams[1].started.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert all(stream.closed for stream in streams)
        assert service.global_active == service.buffer_budget.used == 0
        assert not list((tmp_path / "downloads").glob("*"))
        if service.pool:
            assert all(entry.busy == 0 for entry in service.pool.entries.values())
    finally:
        USE_PROXY.reset(token)
        await close_service(service)
