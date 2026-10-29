import asyncio

import httpx
import pytest

from empire.contracts.download import ResponsePolicy
from empire.contracts.native_stream import StreamTarget
from empire.plugins.collection.unit_prefetch import BorrowedReservation
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.proxy_pool import Endpoint, ProxyPool
from empire.plugins.infra.routing import PROXY_FALLBACK, ROUTE_COUNTS, USE_PROXY


class Permits:
    def __init__(self):
        self.calls = []

    async def eval(self, *args):
        self.calls.append(args)
        return 0


async def echo(reader, writer):
    try:
        writer.write(await reader.readexactly(4))
        await writer.drain()
    finally:
        writer.close()
        await writer.wait_closed()


def service():
    return HttpService(Permits(), 'test', {'ths': {'domains': ['10jqka.com.cn']}})


def target(port):
    return StreamTarget('127.0.0.1', port, 'https://10jqka.com.cn/', ('10jqka.com.cn', '127.0.0.1'))


@pytest.mark.parametrize('host', ['10jqka.com.cn.attacker.invalid', 'evil10jqka.com.cn', '127.0.0.1'])
def test_native_directory_cannot_redirect_to_undeclared_host(host):
    with pytest.raises(ValueError, match='destination domain'):
        StreamTarget(host, 9602, 'https://10jqka.com.cn/', ('10jqka.com.cn', '123ths.com'))


def test_native_directory_domain_can_share_vendor_rate_group():
    value = StreamTarget('hevozhuhq1.123ths.com', 9602,
                         'https://10jqka.com.cn/', ('10jqka.com.cn', '123ths.com'))
    assert value.site_url == 'https://10jqka.com.cn/'


async def test_native_response_owns_shared_budget_until_closed():
    server = await asyncio.start_server(echo, '127.0.0.1', 0)
    http, counts = service(), {}
    tokens = USE_PROXY.set(False), ROUTE_COUNTS.set(counts)

    async def protocol(channel):
        await channel.write(b'test')
        return await channel.readexactly(4)

    try:
        response = await http.request_stream(target(server.sockets[0].getsockname()[1]), protocol,
                                             policy=ResponsePolicy(4, 4))
        assert response.content == b'test'
        assert http.buffer_budget.used == ResponsePolicy(4, 4).reservation_bytes
        assert http.global_active == 0 and http.active['ths'] == 0
        assert counts == {'direct_requests': 1}
        assert len(http.redis.calls) == 1
        response.close()
        response.close()
        assert http.buffer_budget.used == 0 and not http.responses
    finally:
        ROUTE_COUNTS.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
        await http.close()
        server.close()
        await server.wait_closed()


async def test_native_oversize_fails_before_read_without_retries():
    server = await asyncio.start_server(echo, '127.0.0.1', 0)
    http = service()

    async def protocol(channel):
        await channel.write(b'test')
        return await channel.readexactly(5)

    try:
        with pytest.raises(ValueError, match='wire limit'):
            await http.request_stream(target(server.sockets[0].getsockname()[1]), protocol,
                                      policy=ResponsePolicy(4, 4))
        assert len(http.redis.calls) == 1
        assert http.buffer_budget.used == http.global_active == 0
        assert not http.inflight
    finally:
        await http.close()
        server.close()
        await server.wait_closed()


async def test_strict_proxy_never_connects_direct(monkeypatch):
    http = service()
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False)

    async def forbidden(*args, **kwargs):
        pytest.fail('unexpected direct connection')

    monkeypatch.setattr(asyncio, 'open_connection', forbidden)
    try:
        with pytest.raises(RuntimeError, match='代理池未就绪'):
            await http.request_stream(target(9000), forbidden)
        assert http.buffer_budget.used == http.global_active == 0
    finally:
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        await http.close()


async def test_cancel_native_read_releases_route_and_buffer():
    waiting, disconnected = asyncio.Event(), asyncio.Event()

    async def hold(reader, writer):
        try:
            waiting.set()
            await reader.read()
            disconnected.set()
        finally:
            writer.close()
            await writer.wait_closed()

    async def protocol(channel):
        return await channel.readexactly(4)

    server = await asyncio.start_server(hold, '127.0.0.1', 0)
    http = service()
    try:
        task = asyncio.create_task(http.request_stream(target(server.sockets[0].getsockname()[1]), protocol))
        await asyncio.wait_for(waiting.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.wait_for(disconnected.wait(), 2)
        assert http.buffer_budget.used == http.global_active == 0
        assert http.active['ths'] == 0 and not http.inflight
    finally:
        await http.close()
        server.close()
        await server.wait_closed()


async def test_socks_route_uses_remote_destination_and_shared_lease():
    destinations = []

    async def proxy(reader, writer):
        try:
            assert await reader.readexactly(3) == b'\x05\x01\x02'
            writer.write(b'\x05\x02')
            await writer.drain()
            assert await reader.readexactly(1) == b'\x01'
            user = await reader.readexactly((await reader.readexactly(1))[0])
            password = await reader.readexactly((await reader.readexactly(1))[0])
            assert (user, password) == (b'u@name', b'p%word')
            writer.write(b'\x01\x00')
            await writer.drain()
            assert await reader.readexactly(4) == b'\x05\x01\x00\x03'
            host = await reader.readexactly((await reader.readexactly(1))[0])
            port = int.from_bytes(await reader.readexactly(2), 'big')
            destinations.append((host, port))
            writer.write(b'\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x01')
            await writer.drain()
            await echo(reader, writer)
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(proxy, '127.0.0.1', 0)
    entry = Endpoint('test-device', f'socks5h://u%40name:p%25word@127.0.0.1:{server.sockets[0].getsockname()[1]}',
                     'v1', float('inf'), exit_ip='192.0.2.1')

    class Pool:
        closed = False
        open_tunnel = ProxyPool.open_tunnel

        def healthy_count(self):
            return 1

        async def acquire(self, *, site, **kwargs):
            assert not entry.active_sites
            entry.active_sites.add(site)
            return entry

        async def release(self, current, *, site):
            assert current is entry
            entry.active_sites.remove(site)

    http, counts = service(), {}
    http.pool = Pool()
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(False), ROUTE_COUNTS.set(counts)

    async def protocol(channel):
        await channel.write(b'test')
        return await channel.readexactly(4)

    try:
        response = await http.request_stream(StreamTarget('hevo-h.10jqka.com.cn', 8601,
            'https://10jqka.com.cn/', ('10jqka.com.cn',)), protocol)
        assert response.content == b'test'
        response.close()
        assert destinations == [(b'hevo-h.10jqka.com.cn', 8601)]
        assert counts == {'proxy_requests': 1}
        assert not entry.active_sites and entry.requests == 1
        assert http.buffer_budget.used == http.global_active == 0
    finally:
        ROUTE_COUNTS.reset(tokens[2])
        PROXY_FALLBACK.reset(tokens[1])
        USE_PROXY.reset(tokens[0])
        await http.close()
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize('fail', [False, True])
async def test_prefetched_native_response_does_not_double_reserve_or_release_owner(fail):
    server = await asyncio.start_server(echo, '127.0.0.1', 0)
    http, policy = service(), ResponsePolicy(4, 4)
    owner = await http.buffer_budget.reserve(policy.reservation_bytes)
    async def protocol(channel):
        await channel.write(b'test')
        if fail:
            raise ValueError('source validation')
        assert http.buffer_budget.used == policy.reservation_bytes
        return await channel.readexactly(4)
    try:
        if fail:
            with pytest.raises(ValueError, match='source validation'):
                await http.request_stream(target(server.sockets[0].getsockname()[1]), protocol,
                                          policy=policy, reservation=BorrowedReservation(owner))
        else:
            response = await http.request_stream(target(server.sockets[0].getsockname()[1]), protocol,
                                                 policy=policy, reservation=BorrowedReservation(owner))
            response.close()
        assert not owner.released and http.buffer_budget.used == policy.reservation_bytes
        assert http.global_active == 0 and not http.inflight
    finally:
        owner.release()
        await http.close()
        server.close()
        await server.wait_closed()


async def test_stalled_native_peer_uses_bounded_transport_retry_and_cleans_up(monkeypatch):
    from empire.plugins.infra import stream_exchange
    monkeypatch.setattr(stream_exchange, 'ATTEMPT_TIMEOUT_SECONDS', .03)
    monkeypatch.setattr(stream_exchange, 'retry_delay', lambda n: 0)
    clients = []
    async def hold(reader, writer):
        try:
            clients.append(writer)
            await reader.read()
        finally:
            writer.close()
            await writer.wait_closed()
    async def protocol(channel):
        return await channel.readexactly(4)
    server = await asyncio.start_server(hold, '127.0.0.1', 0)
    http = service()
    try:
        with pytest.raises(httpx.ReadTimeout, match='Native exchange'):
            await http.request_stream(target(server.sockets[0].getsockname()[1]), protocol,
                                      max_retries=1, total_timeout=2)
        assert len(clients) == 2 and len(http.redis.calls) == 2
        assert http.buffer_budget.used == http.global_active == 0
        assert not http.inflight and not http.responses
    finally:
        await http.close()
        server.close()
        await server.wait_closed()
