import asyncio

import pytest
from test_stream_exchange import service, target

from empire.contracts.download import ResponsePolicy
from empire.plugins.infra.routing import USE_PROXY


async def test_reuse_keeps_protocol_state_but_each_request_has_own_permit_and_budget():
    accepted = []

    async def peer(reader, writer):
        accepted.append(1)
        try:
            while True:
                writer.write(await reader.readexactly(4))
                await writer.drain()
        except asyncio.IncompleteReadError:
            pass
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(peer, '127.0.0.1', 0)
    http, logins = service(), []
    token = USE_PROXY.set(False)

    async def protocol(channel):
        if not channel.state.get('authenticated'):
            logins.append(1)
            channel.state['authenticated'] = True
        await channel.write(b'data')
        return await channel.readexactly(4)

    destination = target(server.sockets[0].getsockname()[1])
    try:
        for _ in range(3):
            response = await http.request_stream(destination, protocol,
                policy=ResponsePolicy(4, 4), connection_key='generation-1')
            assert response.content == b'data'
            response.close()
            assert http.buffer_budget.used == http.global_active == 0
        assert len(accepted) == len(logins) == 1
        assert len(http.redis.calls) == 3
        response = await http.request_stream(destination, protocol,
            policy=ResponsePolicy(4, 4), connection_key='generation-2')
        response.close()
        assert len(accepted) == len(logins) == 2
        assert http.native_connections.stats['reused'] == 2

        async def bad(channel):
            raise ValueError('bad frame')

        with pytest.raises(ValueError, match='bad frame'):
            await http.request_stream(destination, bad, connection_key='generation-2')
        assert not http.native_connections.idle
        assert http.buffer_budget.used == http.global_active == 0
    finally:
        await http.close()
        USE_PROXY.reset(token)
        server.close()
        await server.wait_closed()
    assert not http.native_connections.idle and not http.native_connections.closing
