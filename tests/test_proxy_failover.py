import asyncio
import time

import httpx
import pytest
from test_proxy_pool import Directory, directory_entry, get, setup

from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


@pytest.mark.parametrize('last_route', ['proxy', 'direct'])
@pytest.mark.parametrize('failure', ['transport', 'authentication'])
async def test_all_failed_devices_are_skipped_without_spending_source_retry_budget(last_route, failure):
    directory = Directory()
    directory.mapping = {f'node{i:03}': directory_entry(f'node{i:03}',
        f'http://user:secret@localhost:{31000 + i}', f'203.0.113.{i}') for i in range(1, 6)}
    directory.expires = {raw: time.monotonic() + 180 for raw in directory.mapping.values()}
    routes = []

    def respond(url, request):
        routes.append(url.rsplit(':', 1)[-1])
        if last_route == 'proxy' and len(routes) == 5:
            return httpx.Response(200, text='proxy')
        if failure == 'authentication':
            return httpx.Response(407)
        raise httpx.ProxyError('credential-bearing failure ' + url)

    pool, service = setup(directory, respond)
    counts = {}
    use, fallback, counting = USE_PROXY.set(True), PROXY_FALLBACK.set(True), ROUTE_COUNTS.set(counts)
    try:
        response = await get(service, max_retries=0)
        assert response.text == last_route
        response.close()
        assert sorted(routes) == [str(31000 + i) for i in range(1, 6)]
        assert counts['proxy_requests'] == 5
        assert counts.get('fallback_requests', 0) == int(last_route == 'direct')
        assert service.global_active == service.buffer_budget.used == 0
        assert all(e.busy == 0 for e in pool.entries.values())
    finally:
        USE_PROXY.reset(use)
        PROXY_FALLBACK.reset(fallback)
        ROUTE_COUNTS.reset(counting)
        await service.close()
        await pool.close()


async def test_exhausted_proxy_only_request_fails_without_direct_or_secret_leak():
    directory = Directory()
    routes = []

    def fail(url, request):
        routes.append(url)
        raise httpx.ProxyError('secret ' + url)

    pool, service = setup(directory, fail)
    use, fallback = USE_PROXY.set(True), PROXY_FALLBACK.set(False)
    try:
        with pytest.raises(httpx.ProxyError, match='禁止本机直连') as caught:
            await get(service, max_retries=0)
        assert 'secret' not in str(caught.value)
        assert len(routes) == 2 and service.stats['sina'].get('direct_requests', 0) == 0
        assert service.global_active == service.buffer_budget.used == 0
    finally:
        USE_PROXY.reset(use)
        PROXY_FALLBACK.reset(fallback)
        await service.close()
        await pool.close()


async def test_failed_device_is_not_reused_after_cooldown_recovers_during_same_request():
    directory = Directory()
    calls = []

    def fail(url, request):
        calls.append(url)
        for entry in pool.entries.values():
            entry.cooldown = 0
        raise httpx.ProxyError('failed')

    pool, service = setup(directory, fail)
    use = USE_PROXY.set(True)
    try:
        response = await get(service, max_retries=0)
        response.close()
        assert len(calls) == 2 and len(set(calls)) == 2
        assert service.stats['sina']['fallback_requests'] == 1
    finally:
        USE_PROXY.reset(use)
        await service.close()
        await pool.close()


async def test_direct_failures_after_failover_still_obey_retry_budget():
    directory = Directory()
    direct_calls = 0

    def proxy_fail(url, request):
        raise httpx.ProxyError('failed')

    def direct_fail(request):
        nonlocal direct_calls
        direct_calls += 1
        raise httpx.ConnectError('direct failed')

    pool, service = setup(directory, proxy_fail, direct=direct_fail)
    use = USE_PROXY.set(True)
    try:
        with pytest.raises(httpx.ConnectError, match='direct failed'):
            await get(service, max_retries=1)
        assert direct_calls == 2
        assert service.stats['sina']['proxy_requests'] == 2
    finally:
        USE_PROXY.reset(use)
        await service.close()
        await pool.close()


async def test_cancel_during_replacement_route_releases_every_permit_and_buffer():
    directory = Directory()
    waiting = asyncio.Event()

    async def respond(url, request):
        if url.endswith('31001'):
            raise httpx.ProxyError('failed')
        waiting.set()
        await asyncio.Event().wait()

    pool, service = setup(directory, respond)
    use = USE_PROXY.set(True)
    task = asyncio.create_task(get(service, max_retries=0))
    try:
        await asyncio.wait_for(waiting.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.global_active == service.buffer_budget.used == 0
        assert all(e.busy == 0 for e in pool.entries.values())
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        USE_PROXY.reset(use)
        await service.close()
        await pool.close()
