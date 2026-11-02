"""Exercise the real frame/route/pool/collector boundary with a local peer."""
import asyncio
from contextlib import suppress
from unittest.mock import AsyncMock

import httpx
import pytest
from test_proxy_pool import Directory, setup
from test_stream_exchange import target
from test_yuanhang_collector import collector

from empire.plugins.infra.routing import PROXY_FALLBACK, USE_PROXY
from empire.sources import yuanhang_client
from empire.sources.yuanhang_auth import GuestSession, IdleConnectionError


def frame(body):
    return b'\xfd' * 4 + f'{len(body):08x}'.encode() + b'\x09' + body


@pytest.mark.parametrize('financial', [False, True])
async def test_backlog_retires_socket_and_reconnects_without_proxy_or_session_rejection(monkeypatch, financial):
    connections, queries, logins, peers = [], [], [], set()

    async def peer(reader, writer):
        peers.add(asyncio.current_task())
        connections.append(writer)
        first = len(connections) == 1
        try:
            while True:
                header = await reader.readexactly(13)
                body = await reader.readexactly(int(header[4:12], 16))
                if body.startswith(b'A'):
                    logins.append(body)
                    writer.write(frame(b'VerifyCode=0\n'))
                else:
                    queries.append(body)
                    writer.write(frame(b'business'))
                    if first and len(queries) == 1:
                        writer.write(frame(b'\0' * 4) * 10)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()
            peers.discard(asyncio.current_task())

    server = await asyncio.start_server(peer, '127.0.0.1', 0)
    pool, http = setup(Directory(), lambda *args: httpx.Response(200))
    destination = target(server.sockets[0].getsockname()[1])
    async def open_tunnel(*args, **kwargs):
        return await asyncio.open_connection(destination.host, destination.port)
    tunnel = AsyncMock(side_effect=open_tunnel)
    monkeypatch.setattr(pool, 'open_tunnel', tunnel)
    failed = pool.failed = AsyncMock()
    c = collector(monkeypatch)
    c.http, c.financial = http, financial
    session = GuestSession('fixture-user', 'fixture-passport', 'fixture-mac', (destination,), 'node001')
    authenticate = AsyncMock(return_value=session)
    async def login(node, **kwargs):
        assert 'rejected' not in kwargs
        return await c.identity.sessions.get(node, 'profile', authenticate)
    c.identity.login = login
    monkeypatch.setattr(yuanhang_client, 'decode_response',
                        lambda body, **kwargs: [{'decoded_bytes': 8}] if body == b'business' else pytest.fail('bad body'))
    for name in ('normalize_daily', 'normalize_financial'):
        monkeypatch.setattr(yuanhang_client, name, lambda *args, **kwargs: 'verified-business')
    tokens = USE_PROXY.set(True), PROXY_FALLBACK.set(True)
    try:
        for _ in range(2):
            result = await c.fetch(('000001.SZ', 'node001', '2026-10-30'))
            assert result.data == 'verified-business'
        assert len(connections) == len(logins) == tunnel.await_count == 2
        assert len(queries) == 3  # warmup, retired exchange, bounded retry
        authenticate.assert_awaited_once()
        failed.assert_not_awaited()
        assert c.stats['idle_connection_retries'] == 1
        assert http.native_connections.stats == dict(opened=2, reused=1, closed=1)
        assert http.buffer_budget.used == http.global_active == 0
        assert not http.responses and not http.inflight
        assert all(not entry.busy for entry in pool.entries.values())
    finally:
        await http.close()
        await pool.close()
        USE_PROXY.reset(tokens[0])
        PROXY_FALLBACK.reset(tokens[1])
        server.close()
        await server.wait_closed()
        if peers:
            await asyncio.wait_for(asyncio.gather(*peers), 2)
    assert not http.native_connections.idle and not http.native_connections.closing


async def test_cancellation_after_idle_failure_is_not_retried(monkeypatch):
    from empire.features.yuanhang import collector as module

    c = collector(monkeypatch)
    fetch = AsyncMock(side_effect=[IdleConnectionError(), asyncio.CancelledError()])
    monkeypatch.setattr(module, 'fetch_history', fetch)
    with pytest.raises(asyncio.CancelledError):
        await c.fetch(('000001.SZ', 'node001', '2026-10-30'))
    assert fetch.await_count == 2
