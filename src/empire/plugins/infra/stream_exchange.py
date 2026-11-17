"""Native exchanges on the existing downloader's route, capacity and byte budget.

The source supplies a bounded protocol exchange; no collector opens sockets.
Sources may explicitly request a reusable connection. This transport does not provision
or bind guest identities; source authentication must establish that contract.
The caller must close the returned response after parsing.
"""
import asyncio

import httpx

from empire.contracts.download import CHUNK_BYTES, BufferedPolicy
from empire.contracts.native_stream import StreamTarget as StreamTarget
from empire.contracts.request_cost import add_cost
from empire.contracts.request_retry import MAX_REQUEST_RETRIES, request_timeout, retry_delay
from empire.plugins.infra.proxy_tunnel import close_writer
from empire.plugins.infra.routing import ProxyRouteError, routed_request

ATTEMPT_TIMEOUT_SECONDS = 30


class BoundedChannel:
    def __init__(self, reader, writer, policy, lease=None, state=None):
        self.reader, self.writer, self.policy, self.lease = reader, writer, policy, lease
        self.received = self.sent = 0
        self.state = state if state is not None else {}

    async def readexactly(self, length):
        if (type(length) is not int or length < 0
                or self.received + length > self.policy.max_wire_bytes):
            raise ValueError("Native response exceeds wire limit")
        if isinstance(self.policy, BufferedPolicy) and (self.lease is None or not self.lease.grow_to(
                3 * (self.received + length) + 4 * CHUNK_BYTES)):
            raise ValueError('共享下载缓冲不足，原生响应未完整读取')
        try:
            data = await self.reader.readexactly(length)
        except asyncio.IncompleteReadError as exc:
            add_cost('observed_wire_bytes', len(exc.partial))
            raise
        self.received += len(data)
        add_cost('observed_wire_bytes', len(data))
        return data

    async def write(self, data):
        if not isinstance(data, bytes) or self.sent + len(data) > 65536:
            raise ValueError("Native request exceeds 64 KiB")
        self.writer.write(data)
        self.sent += len(data)
        await self.writer.drain()


class StreamResponse:
    def __init__(self, content, lease, owner):
        self.content, self.reservation, self.owner = content, lease, owner
        self.decoded_bytes = 0

    def reserve_decoded(self, size):
        if type(size) is not int or size < 0 or self.reservation is None:
            raise ValueError('原生解码预留无效')
        needed = 3 * (len(self.content) + self.decoded_bytes + size) + 4 * CHUNK_BYTES
        if not self.reservation.grow_to(needed):
            raise ValueError('共享下载缓冲不足，原生解压未开始')
        self.decoded_bytes += size

    def close(self):
        self.content = b""
        if self.reservation is not None:
            self.reservation.release()
            self.reservation = None
        self.owner.responses.discard(self)


async def request(service, target, protocol, **kwargs):
    retries = kwargs.get('max_retries', 2)
    if type(retries) is not int or not 0 <= retries <= MAX_REQUEST_RETRIES:
        raise ValueError('Invalid native retry limit')
    timeout = kwargs.get('total_timeout')
    async with asyncio.timeout(request_timeout(retries) if timeout is None else timeout):
        async with service.admit_request(target.site_url, target.allowed_domains):
            return await _request(service, target, protocol, **kwargs)


async def _request(service, target, protocol, *, policy=None, max_retries=2, total_timeout=None,
                  proxy_code=None, reservation=None, connection_key=None, fresh_connection=False):
    """Protocol/auth failures do not retry; transport failures use bounded failover.

    Authentication data is never sent to error-record storage by this layer.
    Sources report sanitized protocol errors through their normal project records.
    """
    if service.closed:
        raise RuntimeError("Downloader has stopped")
    if type(fresh_connection) is not bool:
        raise ValueError('Invalid native fresh-connection flag')
    if type(max_retries) is not int or not 0 <= max_retries <= MAX_REQUEST_RETRIES:
        raise ValueError("Invalid native retry limit")
    group = service.rules.resolve(target.site_url, target.allowed_domains)
    policy = policy or service.response_policy()
    lease = None
    timeout = request_timeout(max_retries) if total_timeout is None else total_timeout

    async def exchange(entry):
        writer = None
        add_cost('native_attempts')
        try:
            # Bound an inactive native peer like HTTP. A source protocol or
            # authentication error remains non-retryable; only transport times out.
            async with asyncio.timeout(ATTEMPT_TIMEOUT_SECONDS):
                if connection_key is not None:
                    async with service.native_connections.connection(
                            target, entry, group.name, connection_key, fresh=fresh_connection) as conn:
                        channel = BoundedChannel(conn.reader, conn.writer, policy, lease, conn.state)
                        content = await protocol(channel)
                        if not isinstance(content, bytes) or len(content) > policy.max_body_bytes:
                            raise ValueError('Native decoded response exceeds body limit')
                    if isinstance(policy, BufferedPolicy) and not lease.grow_to(3 * len(content) + 4 * CHUNK_BYTES):
                        raise ValueError('共享下载缓冲不足，原生响应无法保留')
                    return StreamResponse(content, None, service)
                if entry is None:
                    reader, writer = await asyncio.open_connection(target.host, target.port, limit=16384)
                else:
                    reader, writer = await service.pool.open_tunnel(
                        entry, target.host, target.port, site=group.name,
                    )
                channel = BoundedChannel(reader, writer, policy, lease)
                content = await protocol(channel)
            if not isinstance(content, bytes) or len(content) > policy.max_body_bytes:
                raise ValueError("Native decoded response exceeds body limit")
            if isinstance(policy, BufferedPolicy) and not lease.grow_to(3 * len(content) + 4 * CHUNK_BYTES):
                raise ValueError('共享下载缓冲不足，原生响应无法保留')
            return StreamResponse(content, None, service)
        except TimeoutError:
            raise httpx.ReadTimeout('Native exchange timed out') from None
        except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            raise httpx.ConnectError(f"Native transport failure ({type(exc).__name__})") from None
        finally:
            if writer is not None:
                await close_writer(writer)

    try:
        async with asyncio.timeout(timeout):
            if reservation is not None:
                if (reservation.budget is not service.buffer_budget or reservation.released
                        or (reservation.size < policy.reservation_bytes if isinstance(policy, BufferedPolicy)
                            else reservation.size != policy.reservation_bytes)):
                    raise ValueError('响应缓冲预留与请求策略不一致')
                lease = reservation
            else:
                lease = await service.buffer_budget.reserve(policy.reservation_bytes)
            excluded: set[str] = set()
            retries = 0
            while True:
                try:
                    response = await routed_request(service, "STREAM", target.site_url,
                        target.allowed_domains, excluded_proxies=excluded, exchange=exchange,
                        proxy_code=proxy_code)
                    response.reservation, lease = lease, None
                    service.responses.add(response)
                    return response
                except ProxyRouteError as exc:
                    if proxy_code is not None:
                        # A node-bound session cannot move to another account or
                        # wait on its own excluded node; the session owner decides.
                        raise
                    excluded.add(exc.code)
                    add_cost('retries')
                except httpx.TransportError:
                    if retries >= max_retries:
                        raise
                    retries += 1
                    add_cost('retries')
                    await asyncio.sleep(retry_delay(retries))
    finally:
        if lease is not None and reservation is None:
            lease.release()
