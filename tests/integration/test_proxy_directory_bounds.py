"""Real directory Lua on owned keys; never modifies RouterProxy's directory."""
import json
import os
from ipaddress import IPv4Address
from uuid import uuid4

import httpx
import pytest

from empire.core.config import load_config
from empire.plugins.infra.proxy_pool import DIRECTORY, ProxyPool
from empire.plugins.infra.redis_store import create_client

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Explicit integration opt-in required')]


async def test_directory_capacity_limits_and_candidate_recheck():
    client = create_client(load_config()['redis'])
    prefix = 'empire:test:directory-bound:' + uuid4().hex
    mapping, leases = prefix + ':mapping', prefix + ':leases'
    pool = ProxyPool(client, mapping_key=mapping, directory_key=leases,
                     client_factory=lambda _: httpx.AsyncClient())

    async def populate(count, padding=0):
        seconds, micros = await client.time()
        deadline = seconds + micros / 1000000 + 300
        values = {f'n{i}': json.dumps({'code': f'n{i}', 'proxy': 'u:private@localhost:9',
            'exit_ip': str(IPv4Address(0x0A000001 + i)), 'padding': 'x' * padding})
                  for i in range(count)}
        async with client.pipeline(transaction=True) as pipe:
            pipe.delete(mapping, leases)
            pipe.hset(mapping, mapping=values)
            pipe.zadd(leases, {raw: deadline for raw in values.values()})
            await pipe.execute()

    try:
        for count in (1000, 1001, 3000, 5000):
            await populate(count)
            await pool.refresh()
            assert len(pool.entries) == count and pool.healthy_egress_count() == count
            assert not pool.error
        await populate(5001)
        await pool.refresh()
        assert pool.directory_limited and len(pool.entries) == 5000
        assert 'private' not in pool.error
        entry = await pool.acquire(site='test', fallback=True, device_code='n0')
        await pool.release(entry, site='test')
        # Unknown inventory must not silently authorize a direct connection.
        empty = ProxyPool(client, mapping_key=mapping, directory_key=leases)
        await empty.refresh()
        with pytest.raises(httpx.ProxyError, match='5000'):
            await empty.acquire(fallback=True)
        await empty.close()
        await populate(3000, padding=3000)
        await pool.refresh()
        assert pool.directory_limited
        # Oversize individual entries are invalid, never returned as raw bodies.
        await populate(1, padding=4096)
        result = await client.eval(DIRECTORY, 2, mapping, leases)
        assert result == ['n0', '', result[2]]
        await pool.refresh()
        assert pool.invalid == 1 and not pool.entries and not pool.directory_limited
    finally:
        await pool.close()
        await client.delete(mapping, leases)
        await client.aclose()
