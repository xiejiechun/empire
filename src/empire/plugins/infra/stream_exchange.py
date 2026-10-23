"""Native exchanges on the existing downloader's route, capacity and byte budget.

The source supplies a bounded protocol exchange; no collector opens sockets.
Connections are per exchange and are not pooled. This transport does not provision
or bind guest identities; source authentication must establish that contract.
The caller must close the returned response after parsing.
"""
import asyncio

import httpx

from empire.contracts.native_stream import StreamTarget as StreamTarget
from empire.contracts.request_retry import MAX_REQUEST_RETRIES, request_timeout, retry_delay
from empire.plugins.infra.proxy_tunnel import close_writer
from empire.plugins.infra.routing import ProxyRouteError, routed_request


class BoundedChannel:
    def __init__(self, reader, writer, policy):
        self.reader, self.writer, self.policy = reader, writer, policy
        self.received = self.sent = 0

    async def readexactly(self, length):
        if (type(length) is not int or length < 0
                or self.received + length > self.policy.max_wire_bytes):
            raise ValueError("Native response exceeds wire limit")
        data = await self.reader.readexactly(length)
        self.received += len(data)
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

    def close(self):
        self.content = b""
        if self.reservation is not None:
            self.reservation.release()
            self.reservation = None
        self.owner.responses.discard(self)


async def request(service, target, protocol, *, policy=None, max_retries=2, total_timeout=None):
    """Protocol/auth failures do not retry; transport failures use bounded failover.

    Authentication data is never sent to error-record storage by this layer.
    Sources report sanitized protocol errors through their normal project records.
    """
    if service.closed:
        raise RuntimeError("Downloader has stopped")
    if type(max_retries) is not int or not 0 <= max_retries <= MAX_REQUEST_RETRIES:
        raise ValueError("Invalid native retry limit")
    group = service.rules.resolve(target.site_url, target.allowed_domains)
    policy = policy or service.response_policy()
    task, lease = asyncio.current_task(), None
    service.inflight.add(task)
    timeout = request_timeout(max_retries) if total_timeout is None else total_timeout

    async def exchange(entry):
        writer = None
        try:
            if entry is None:
                reader, writer = await asyncio.open_connection(target.host, target.port, limit=16384)
            else:
                reader, writer = await service.pool.open_tunnel(
                    entry, target.host, target.port, site=group.name,
                )
            channel = BoundedChannel(reader, writer, policy)
            content = await protocol(channel)
            if not isinstance(content, bytes) or len(content) > policy.max_body_bytes:
                raise ValueError("Native decoded response exceeds body limit")
            return StreamResponse(content, None, service)
        except (OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
            raise httpx.ConnectError(f"Native transport failure ({type(exc).__name__})") from None
        finally:
            if writer is not None:
                await close_writer(writer)

    try:
        async with asyncio.timeout(timeout):
            lease = await service.buffer_budget.reserve(policy.reservation_bytes)
            excluded, retries = set(), 0
            while True:
                try:
                    response = await routed_request(service, "STREAM", target.site_url,
                        target.allowed_domains, excluded_proxies=excluded, exchange=exchange)
                    response.reservation, lease = lease, None
                    service.responses.add(response)
                    return response
                except ProxyRouteError as exc:
                    excluded.add(exc.code)
                except httpx.TransportError:
                    if retries >= max_retries:
                        raise
                    retries += 1
                    await asyncio.sleep(retry_delay(retries))
    finally:
        if lease is not None:
            lease.release()
        service.inflight.discard(task)
