"""Each site owns every egress slot, including through the real proxy transport."""
import asyncio
import base64
import time
from urllib.parse import urlsplit

import httpx
import pytest

from empire.plugins.infra.http import HttpService
from empire.plugins.infra.proxy_pool import ProxyPool
from empire.plugins.infra.routing import USE_PROXY
from tests.test_proxy_pool import Directory, directory_entry


@pytest.mark.parametrize('global_limit,cancel', [(128, False), (9, False), (128, True)])
async def test_seven_exits_for_each_site_and_shared_global_limit(global_limit, cancel):
    release, reached = asyncio.Event(), asyncio.Event()
    active, pairs, peak, handlers = {}, set(), {}, set()
    expected = min(14, global_limit)

    async def proxy(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        pair = None
        try:
            headers = (await reader.readuntil(b'\r\n\r\n')).decode()
            host = urlsplit(headers.split(' ', 2)[1]).hostname
            auth = next(line.split(': ', 1)[1] for line in headers.split('\r\n')
                        if line.lower().startswith('proxy-authorization:'))
            device = base64.b64decode(auth.split(' ', 1)[1]).decode().split(':', 1)[0]
            pair = (host, device)
            assert pair not in pairs
            pairs.add(pair)
            active[host] = active.get(host, 0) + 1
            peak[host] = max(peak.get(host, 0), active[host])
            if len(pairs) == expected:
                reached.set()
            await release.wait()
            writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}')
            await writer.drain()
        finally:
            if pair is not None:
                pairs.remove(pair)
                active[pair[0]] -= 1
            writer.close()
            await writer.wait_closed()
            handlers.discard(task)

    server = await asyncio.start_server(proxy, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    directory = Directory()
    directory.mapping = {f'node{i}': directory_entry(f'node{i}',
        f'http://node{i}:test@127.0.0.1:{port}', f'203.0.113.{i}') for i in range(1, 8)}
    directory.expires = {raw: time.monotonic() + 180 for raw in directory.mapping.values()}
    pool = ProxyPool(directory)
    groups = {site: dict(domains=[site + '.test'], scaling_mode='auto',
        min_interval_ms=100, proxy_interval_ms=100, total_interval_ms=100,
        max_concurrency=0) for site in ('ths', 'kaipanla')}
    http = HttpService(directory, 'cross-site-test', groups, pool=pool,
                       resources={'max_parallel_downloads': global_limit})
    tasks = []
    token = USE_PROXY.set(True)

    async def get(site):
        response = await http.request('GET', 'http://' + site + '.test/',
                                     allowed_domains=(site + '.test',), max_retries=0)
        response.close()

    try:
        tasks = [asyncio.create_task(get(site)) for site in groups for _ in range(7)]
        await asyncio.wait_for(reached.wait(), 5)
        assert http.global_active == expected
        if global_limit >= 14:
            assert active == {'ths.test': 7, 'kaipanla.test': 7}
            assert all(entry.busy == 2 for entry in pool.entries.values())
        assert all(count <= 7 for count in active.values())
        if cancel:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            release.set()
            await asyncio.wait_for(asyncio.gather(*tasks), 5)
        assert http.global_peak <= global_limit
        assert http.global_active == http.buffer_budget.used == 0
        assert all(not entry.active_sites for entry in pool.entries.values())
    finally:
        USE_PROXY.reset(token)
        release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await http.close()
        await pool.close()
        server.close()
        await server.wait_closed()
        await asyncio.gather(*handlers, return_exceptions=True)


async def test_retired_connection_waits_for_every_site_and_release_is_scoped():
    directory = Directory()
    directory.mapping.pop('node002')
    pool = ProxyPool(directory, client_factory=lambda url: httpx.AsyncClient())
    first = await pool.acquire(site='ths')
    second = await asyncio.wait_for(pool.acquire(site='kaipanla'), 1)
    assert first is second and first.busy == 2
    client = first.client
    directory.mapping.clear()
    await pool.refresh()
    try:
        with pytest.raises(RuntimeError):
            await pool.release(first, site='sina')
        await pool.release(first, site='ths')
        assert first.active_sites == {'kaipanla'} and not client.is_closed
        with pytest.raises(RuntimeError):
            await pool.release(first, site='ths')
        await pool.release(second, site='kaipanla')
        await pool._reap()
        assert client.is_closed
    finally:
        for site in tuple(first.active_sites):
            await pool.release(first, site=site)
        await pool.close()


async def test_one_sites_429_does_not_cool_other_sites_on_same_device():
    directory = Directory()
    directory.mapping.pop('node002')
    pool = ProxyPool(directory, client_factory=lambda url: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            429 if request.url.host == 'ths.test' else 200, headers={'Retry-After': '1'}))))
    groups = {site: dict(domains=[site + '.test'], scaling_mode='auto',
        min_interval_ms=100, proxy_interval_ms=100, total_interval_ms=100,
        max_concurrency=0) for site in ('ths', 'kaipanla')}
    http = HttpService(directory, 'cross-site-test', groups, pool=pool)
    token = USE_PROXY.set(True)
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await http.request('GET', 'http://ths.test/', allowed_domains=('ths.test',), max_retries=0)
        response = await asyncio.wait_for(http.request('GET', 'http://kaipanla.test/',
            allowed_domains=('kaipanla.test',), max_retries=0), .5)
        response.close()
        assert 'cross-site-test:rate:ths' in directory.cooldowns
        assert 'cross-site-test:rate:kaipanla' not in directory.cooldowns
        assert http.global_active == http.buffer_budget.used == 0
    finally:
        USE_PROXY.reset(token)
        await http.close()
        await pool.close()
