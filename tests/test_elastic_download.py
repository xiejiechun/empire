"""Real streaming through the shared reader; no old category ceiling or disk spill."""
import asyncio
import gzip

import httpx
import pytest

from empire.contracts.download import CHUNK_BYTES, MiB
from empire.plugins.collection.prefetch import ordered_prefetch
from empire.plugins.collection.unit_prefetch import BorrowedReservation
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.response_reader import DownloadLimitError
from tests.test_download_resources import RawStream
from tests.test_download_settings import Permits


def service(body, budget=64 * MiB, encoding='identity'):
    encoded = gzip.compress(body) if encoding == 'gzip' else body
    streams, requests = [], []

    def respond(request):
        requests.append(request.url)
        stream = RawStream([encoded[i:i + CHUNK_BYTES] for i in range(0, len(encoded), CHUNK_BYTES)])
        streams.append(stream)
        return httpx.Response(200, stream=stream, headers={'content-encoding': encoding})
    return HttpService(Permits(), 'test', {}, resources={'buffer_budget_bytes': budget,
        'stock_response_bytes': 1024, 'generic_response_bytes': 1024},
        transport=httpx.MockTransport(respond)), streams, requests


@pytest.mark.parametrize('profile', ['stocks', 'news', 'calendar', 'generic'])
@pytest.mark.parametrize('encoding', ['identity', 'gzip'])
async def test_large_complete_response_grows_and_releases(profile, encoding):
    payload = b'01234567' * (10 * MiB // 8)
    http, streams, requests = service(payload, encoding=encoding)
    try:
        policy = http.response_policy(profile)
        assert policy.reservation_bytes == 256 * 1024
        r = await http.request('GET', 'https://example.test/', allowed_domains=('example.test',), policy=policy)
        assert r.content == payload and len(requests) == 1
        assert http.buffer_budget.used == 3 * len(payload) + 256 * 1024
        assert http.buffer_budget.peak <= http.buffer_budget.limit
        r.close()
        assert http.buffer_budget.used == 0 and all(s.closed for s in streams)
    finally:
        await http.close()


async def test_contention_is_bounded_failure_not_hold_and_wait_or_retry():
    http, streams, requests = service(b'x' * (512 * 1024), budget=2 * MiB)
    try:
        first = await http.request('GET', 'https://example.test/1', allowed_domains=('example.test',))
        retained = http.buffer_budget.used
        with pytest.raises(DownloadLimitError, match='共享下载缓冲不足') as failure:
            await asyncio.wait_for(http.request('GET', 'https://example.test/2',
                allowed_domains=('example.test',), max_retries=5), 2)
        assert len(requests) == 2 and len(failure.value.sample) <= CHUNK_BYTES
        assert http.buffer_budget.used == retained and all(s.closed for s in streams)
        assert first.content == b'x' * (512 * 1024)
        first.close()
        assert http.buffer_budget.used == 0
    finally:
        await http.close()


@pytest.mark.parametrize('encoding', ['identity', 'gzip'])
async def test_single_body_beyond_total_budget_never_returns_partial(encoding):
    http, streams, requests = service(b'x' * MiB, budget=2 * MiB, encoding=encoding)
    try:
        with pytest.raises(DownloadLimitError, match='共享下载缓冲'):
            await http.request('GET', 'https://example.test/', allowed_domains=('example.test',), max_retries=3)
        assert len(requests) == 1 and all(s.closed for s in streams)
        assert http.buffer_budget.used == 0
    finally:
        await http.close()


async def test_ordered_owner_retains_dynamic_bytes_and_cancel_releases():
    payload = b'x' * MiB
    http, _, _ = service(payload)
    leases = []
    async def width(): return 2
    async def fetch(number, lease):
        leases.append(lease)
        return await http.request('GET', f'https://host{number}.test/',
            allowed_domains=(f'host{number}.test',),
            reservation=BorrowedReservation(lease, http.response_policy().reservation_bytes))
    try:
        async with ordered_prefetch(0, 1, fetch, width, budget=http.buffer_budget,
                reservation_bytes=http.response_policy().reservation_bytes) as reads:
            async for _, response in reads:
                assert response.content == payload
                assert http.buffer_budget.used >= 3 * MiB + 256 * 1024
                break
        assert http.buffer_budget.used == 0 and all(lease.released for lease in leases)
        assert not http.inflight and not http.responses
    finally:
        await http.close()


async def test_cancel_after_growth_releases_actual_allocation_and_transport():
    stream = RawStream([b'x' * CHUNK_BYTES] * 10, block_after=2)
    http = HttpService(Permits(), 'test', {}, transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)))
    task = asyncio.create_task(http.request('GET', 'https://example.test/', allowed_domains=('example.test',)))
    try:
        async with asyncio.timeout(2):
            while stream.reads < 2:
                await asyncio.sleep(0)
        assert http.buffer_budget.used == 256 * 1024 + 6 * CHUNK_BYTES
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert stream.closed and http.buffer_budget.used == 0
        assert not http.inflight and http.global_active == 0
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await http.close()


async def test_native_channel_reserves_before_read_and_decoding():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from empire.plugins.infra.stream_exchange import BoundedChannel, StreamResponse
    from empire.sources.yuanhang_wire import snappy_block

    http, _, _ = service(b'', budget=2 * MiB)
    lease = await http.buffer_budget.reserve(http.response_policy().reservation_bytes)
    reader = SimpleNamespace(readexactly=AsyncMock(side_effect=lambda n: b'x' * n))
    channel = BoundedChannel(reader, None, http.response_policy(), lease)
    try:
        assert len(await channel.readexactly(256 * 1024)) == 256 * 1024
        assert http.buffer_budget.used == MiB
        with pytest.raises(ValueError, match='共享下载缓冲'):
            await channel.readexactly(MiB)
        assert reader.readexactly.await_count == 1
        r = StreamResponse(b'x' * (256 * 1024), lease, http)
        # Header advertises 1MiB; refusal occurs before malformed payload parsing/allocation.
        with pytest.raises(ValueError, match='原生解压未开始'):
            snappy_block(b'\x80\x80\x40', 2 * MiB, r.reserve_decoded)
        r.close()
        assert http.buffer_budget.used == 0
    finally:
        lease.release()
        await http.close()


async def test_indices_stricter_source_policy_keeps_elastic_prefetch_lease():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from empire.features.indices.collector import ThsIndexCollector

    http, _, _ = service(b'valid source')
    collector = ThsIndexCollector()
    collector.http = http
    collector.ingest = SimpleNamespace(ensure_capacity=AsyncMock())
    collector.session = SimpleNamespace(headers=lambda url: {})
    owner = await http.buffer_budget.reserve(http.response_policy().reservation_bytes)
    try:
        result = await collector.fetch('https://q.10jqka.com.cn/zs/', lambda body: body,
            reservation=BorrowedReservation(owner, http.response_policy().reservation_bytes), defer=True)
        assert await result.consume() == 'valid source'
        result.close()
        assert http.buffer_budget.used > 256 * 1024
    finally:
        owner.release()
        await http.close()
    assert http.buffer_budget.used == 0
