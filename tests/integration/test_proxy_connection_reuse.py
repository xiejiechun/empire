"""Several sites reuse independent origin connections through one device."""
import asyncio
import json
import os
from collections import Counter
from uuid import uuid4

import pytest

from empire.core.config import load_config
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.proxy_pool import ProxyPool
from empire.plugins.infra.redis_store import create_client
from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit isolated integration opt-in')]


async def test_two_origins_reuse_both_connections_without_device_churn():
    client = create_client(load_config()['redis'])
    prefix = 'empire:test:origin-reuse:' + uuid4().hex
    mapping, leases = prefix + ':mapping', prefix + ':leases'
    counts, handlers = Counter(), set()

    async def proxy(reader, writer):
        task = asyncio.current_task()
        handlers.add(task)
        counts['opened'] += 1
        try:
            while True:
                try:
                    header = await reader.readuntil(b'\r\n\r\n')
                except (asyncio.IncompleteReadError, ConnectionError):
                    break
                host = header.decode('ascii').splitlines()[0].split()[1].split('/')[2]
                counts[host] += 1
                writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: keep-alive\r\n\r\nok')
                await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            counts['closed'] += 1
            handlers.discard(task)

    server = await asyncio.start_server(proxy, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]
    pool = ProxyPool(client, mapping_key=mapping, directory_key=leases)
    service = HttpService(client, prefix, {
        host: dict(domains=[host + '.test'], scaling_mode='auto', max_concurrency=0,
                   min_interval_ms=100, proxy_interval_ms=100, total_interval_ms=100)
        for host in ('one', 'two')}, pool=pool)
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False)
    try:
        seconds, micros = await client.time()
        raw = json.dumps(dict(code='one', proxy=f'http://u:fixture@127.0.0.1:{port}', exit_ip='10.0.0.1'))
        await client.hset(mapping, mapping={'one': raw})
        await client.zadd(leases, {raw: seconds + micros / 1e6 + 60})
        await pool.refresh()
        async with asyncio.timeout(15):
            for _ in range(6):
                for host in ('one', 'two'):
                    response = await service.request('GET', 'http://' + host + '.test/data',
                        allowed_domains=(host + '.test',), max_retries=0)
                    try:
                        assert response.content == b'ok'
                    finally:
                        response.close()
        assert counts['one.test'] == counts['two.test'] == 6
        assert counts['opened'] == 2
        assert service.global_active == service.buffer_budget.used == 0
    finally:
        await service.close()
        await pool.close()
        server.close()
        await server.wait_closed()
        await asyncio.wait_for(asyncio.gather(*handlers), 5)
        assert counts['opened'] == counts['closed']
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        keys = [key async for key in client.scan_iter(match=prefix + ':*')]
        if keys:
            assert all(key.startswith(prefix + ':') for key in keys)
            await client.delete(*keys)
        await client.aclose()
