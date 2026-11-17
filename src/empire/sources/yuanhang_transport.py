"""Shared authenticated Yuanhang exchange on the bounded native downloader."""
from empire.contracts.request_cost import add_cost
from empire.sources.yuanhang_auth import exchange_frame, login_native


async def request(http, session, query, decoder, *, project_id, reservation=None, service=None):
    policy = http.response_policy('generic')
    target = session.targets_for(service)[0] if service else session.servers[0]

    async def exchange(channel):
        if not channel.state.get('yuanhang_authenticated'):
            await login_native(channel, session)
            add_cost('native_auth_exchanges')
            channel.state['yuanhang_authenticated'] = True
        add_cost('native_queries')
        return await exchange_frame(channel, query, allow_idle=True)

    response = await http.request_stream(target, exchange, policy=policy,
        proxy_code=session.proxy_code, max_retries=0, connection_key=session, reservation=reservation)
    try:
        return decoder(response.content, policy.max_body_bytes, response.reserve_decoded)
    finally:
        response.close()
