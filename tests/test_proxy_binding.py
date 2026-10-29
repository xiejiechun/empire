import asyncio
import time

import httpx
import pytest
from test_proxy_pool import Directory, directory_entry, get, setup

from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY


@pytest.mark.parametrize('failure', [None, 'transport', 'missing'])
async def test_fixed_node_never_changes_device_or_falls_back(failure):
    directory, calls = Directory(), []
    if failure == 'missing':
        directory.mapping.pop('node002')

    def respond(url, request):
        calls.append(url.rsplit(':', 1)[-1])
        if failure == 'transport':
            raise httpx.ConnectError('unreachable')
        return httpx.Response(200)

    def direct(request):
        pytest.fail('Bound identity leaked to direct route')

    pool, service = setup(directory, respond, direct=direct)
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True)
    try:
        if failure:
            with pytest.raises(httpx.ProxyError, match='绑定'):
                await get(service, proxy_code='node002', max_retries=0)
        else:
            result = await get(service, proxy_code='node002')
            result.close()
        assert calls == ([] if failure == 'missing' else ['31002'])
        assert service.global_active == service.buffer_budget.used == 0
        assert all(not entry.busy for entry in pool.entries.values())
    finally:
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        await service.close()
        await pool.close()


async def test_fixed_node_waits_for_shared_egress_and_reuses_code_after_ip_change():
    directory = Directory()
    directory.mapping['node002'] = directory_entry('node002', 'socks5h://u:p@localhost:31002', '203.0.113.1')
    directory.expires[directory.mapping['node002']] = time.monotonic() + 180
    pool, service = setup(directory, lambda *args: httpx.Response(200))
    try:
        first = await pool.acquire(site='ths', device_code='node001')
        pending = asyncio.create_task(pool.acquire(site='ths', device_code='node002'))
        await asyncio.sleep(.02)
        assert not pending.done()
        await pool.release(first, site='ths')
        second = await asyncio.wait_for(pending, 2)
        assert second.code == 'node002'
        await pool.release(second, site='ths')
        raw = directory_entry('node002', 'socks5h://u:p@localhost:31003', '203.0.113.9')
        directory.mapping['node002'], directory.expires[raw] = raw, time.monotonic() + 180
        await pool.refresh()
        changed = await pool.acquire(site='ths', device_code='node002')
        assert changed.code == second.code and changed.exit_ip != second.exit_ip
        await pool.release(changed, site='ths')
    finally:
        await service.close()
        await pool.close()
