"""Real raw streams exercise limits before httpx can buffer/decompress responses."""
import asyncio
import gzip
import hashlib
import threading
import zlib
from types import SimpleNamespace

import httpx
import pytest
from test_http import ErrorRecorder, MemoryPermits, groups
from test_proxy_pool import Directory

from empire.contracts.download import CHUNK_BYTES, FilePolicy, ResponsePolicy
from empire.plugins.infra.download_storage import FileSink
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.proxy_pool import ProxyPool
from empire.plugins.infra.resources import ByteBudget
from empire.plugins.infra.response_reader import DownloadLimitError, read_response
from empire.plugins.infra.routing import USE_PROXY

URL = "https://finance.sina.com.cn/data"
ALLOWED = ("sina.com.cn",)


class RawStream(httpx.AsyncByteStream):
    def __init__(self, blocks=(), *, block_after=None):
        self.blocks = list(blocks)
        self.block_after = block_after
        self.started = asyncio.Event()
        self.proceed = asyncio.Event()
        self.reads = 0
        self.closed = False

    async def __aiter__(self):
        self.started.set()
        for index, block in enumerate(self.blocks):
            if index == self.block_after:
                await self.proceed.wait()
            await asyncio.sleep(0)
            self.reads += 1
            yield block

    async def aclose(self):
        self.closed = True


def service_for(tmp_path, respond, *, records=None, buffer_bytes=4 * 1024 * 1024, pool=None):
    return HttpService(MemoryPermits(), "test", groups(1), records=records, pool=pool,
                       transport=httpx.MockTransport(respond), resources={
                           "buffer_budget_bytes": buffer_bytes,
                           "download_directory": tmp_path / "downloads",
                           "download_quota_bytes": 20 * 1024 * 1024,
                           "disk_free_margin_bytes": 0,
                       })


async def get(service, policy, **kwargs):
    return await service.request("GET", URL, allowed_domains=ALLOWED, policy=policy,
                                 project_id="sina-stocks", max_retries=0, **kwargs)


@pytest.mark.parametrize("encoding", ["identity", "gzip", "deflate"])
async def test_stream_decoding_matches_bytes_and_lease_survives_until_close(tmp_path, encoding):
    payload = b'{"rows":' + b"[1,2,3]" * 700 + b"}"
    encoded = {"identity": payload, "gzip": gzip.compress(payload), "deflate": zlib.compress(payload)}[encoding]
    stream = RawStream([encoded[i:i + 7] for i in range(0, len(encoded), 7)])
    policy = ResponsePolicy(max_body_bytes=10000, max_wire_bytes=10000)
    service = service_for(tmp_path, lambda request: httpx.Response(200,
        headers={"Content-Encoding": encoding, "Content-Length": str(len(encoded))}, stream=stream))
    try:
        response = await get(service, policy)
        assert stream.closed and response.content == payload
        assert "content-encoding" not in response.headers
        assert response.extensions["download"] == {"wire_bytes": len(encoded),
            "body_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        assert service.buffer_budget.used == policy.reservation_bytes
        response.close()
        assert not response.content and service.buffer_budget.used == 0
        assert b"".join(response.stream) == b""
        response.close()
        assert service.buffer_budget.used == 0
    finally:
        await service.close()


@pytest.mark.parametrize("headers,blocks,error,read_count", [
    ({}, [b"abc", b"def"], "正文", 2),
    ({"Content-Length": "2"}, [b"abc"], "长度与声明不一致", 1),
    ({"Content-Length": "100"}, [b"abc"], "声明长度", 0),
    ({"Content-Length": "-1"}, [b"abc"], "Content-Length", 0),
    ({"Content-Encoding": "br"}, [b"abc"], "未支持", 0),
])
async def test_unknown_false_and_invalid_headers_never_bypass_body_limits(
        tmp_path, headers, blocks, error, read_count):
    stream = RawStream(blocks)
    records = ErrorRecorder()
    service = service_for(tmp_path, lambda request: httpx.Response(200, headers=headers, stream=stream), records=records)
    try:
        with pytest.raises(DownloadLimitError, match=error) as caught:
            await get(service, ResponsePolicy(max_body_bytes=5, max_wire_bytes=10))
        assert stream.closed and stream.reads == read_count
        assert service.buffer_budget.used == 0
        assert len(records.errors) == 1 and caught.value.diagnostic_recorded
        assert records.errors[0]["raw_body_complete"] is False
        assert len(records.errors[0]["raw_body"]) <= CHUNK_BYTES
    finally:
        await service.close()


async def test_wire_limit_stops_stream_without_reading_remaining_blocks(tmp_path):
    stream = RawStream([b"1234", b"5678", b"should-not-be-read"])
    service = service_for(tmp_path, lambda request: httpx.Response(200, stream=stream))
    try:
        with pytest.raises(DownloadLimitError, match="实际传输"):
            await get(service, ResponsePolicy(max_body_bytes=100, max_wire_bytes=5))
        assert stream.reads == 2 and stream.closed
        assert service.buffer_budget.used == 0
    finally:
        await service.close()


async def test_gzip_expansion_never_requests_unbounded_decoder_output(tmp_path, monkeypatch):
    encoded = gzip.compress(b"z" * (3 * 1024 * 1024))
    stream = RawStream([encoded])
    original = zlib.decompressobj
    output_sizes = []

    class BoundedDecoder:
        def __init__(self, *args):
            self.decoder = original(*args)

        def decompress(self, chunk, max_length=0):
            assert 0 < max_length <= CHUNK_BYTES and len(chunk) <= CHUNK_BYTES
            output = self.decoder.decompress(chunk, max_length)
            output_sizes.append(len(output))
            return output

        def __getattr__(self, name):
            return getattr(self.decoder, name)

    monkeypatch.setattr("empire.plugins.infra.response_reader.zlib.decompressobj", BoundedDecoder)
    service = service_for(tmp_path, lambda request: httpx.Response(200,
        headers={"Content-Encoding": "gzip"}, stream=stream))
    try:
        with pytest.raises(DownloadLimitError, match="正文") as caught:
            await get(service, ResponsePolicy(max_body_bytes=2 * CHUNK_BYTES, max_wire_bytes=CHUNK_BYTES))
        assert max(output_sizes) <= CHUNK_BYTES
        assert caught.value.observed_bytes == 3 * CHUNK_BYTES
        assert len(caught.value.sample) == CHUNK_BYTES
        assert stream.closed and service.buffer_budget.used == 0
    finally:
        await service.close()


@pytest.mark.parametrize("encoded", [gzip.compress(b"abc")[:-3], b"broken-gzip",
                                      gzip.compress(b"abc") + gzip.compress(b"def")])
async def test_corrupt_truncated_and_extra_gzip_members_do_not_succeed(tmp_path, encoded):
    stream = RawStream([encoded])
    service = service_for(tmp_path, lambda request: httpx.Response(200,
        headers={"Content-Encoding": "gzip"}, stream=stream))
    try:
        with pytest.raises(DownloadLimitError):
            await get(service, ResponsePolicy(max_body_bytes=1000, max_wire_bytes=1000))
        assert stream.closed and not service.responses and service.buffer_budget.used == 0
    finally:
        await service.close()


async def test_budget_wait_does_not_hold_request_permit_and_cancellation_is_clean(tmp_path):
    policy = ResponsePolicy(max_body_bytes=100, max_wire_bytes=100)
    streams = []

    def respond(request):
        stream = RawStream([b"{}"])
        streams.append(stream)
        return httpx.Response(200, stream=stream)

    service = service_for(tmp_path, respond, buffer_bytes=policy.reservation_bytes)
    try:
        first = await get(service, policy)
        blocked = asyncio.create_task(get(service, policy))
        await asyncio.sleep(.01)
        assert service.buffer_budget.waiting == 1 and len(streams) == 1
        blocked.cancel()
        with pytest.raises(asyncio.CancelledError):
            await blocked
        assert service.buffer_budget.waiting == 0 and service.buffer_budget.used == policy.reservation_bytes
        next_request = asyncio.create_task(get(service, policy))
        await asyncio.sleep(.01)
        first.close()
        second = await asyncio.wait_for(next_request, 1)
        assert len(streams) == 2 and service.buffer_budget.peak == policy.reservation_bytes
        second.close()
        assert service.buffer_budget.used == 0
    finally:
        await service.close()


async def test_service_shutdown_cancels_stream_and_reclaims_all_reservations(tmp_path):
    stream = RawStream([b"a", b"b"], block_after=1)
    service = service_for(tmp_path, lambda request: httpx.Response(200, stream=stream))
    task = asyncio.create_task(get(service, ResponsePolicy(max_body_bytes=100, max_wire_bytes=100)))
    await stream.started.wait()
    await service.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed and service.buffer_budget.used == 0 and not service.inflight


async def test_429_cooldown_is_applied_before_oversized_body_is_rejected(tmp_path):
    stream = RawStream([b"too much"])
    service = service_for(tmp_path, lambda request: httpx.Response(429,
        headers={"Retry-After": "30", "Content-Length": "9999"}, stream=stream))
    try:
        with pytest.raises(DownloadLimitError):
            await get(service, ResponsePolicy(max_body_bytes=100, max_wire_bytes=100))
        assert "test:rate:sina" in service.redis.cooldown
        assert stream.closed and stream.reads == 0 and service.buffer_budget.used == 0
    finally:
        await service.close()


async def test_oversized_proxy_response_does_not_isolate_or_retry_device(tmp_path):
    directory = Directory()
    streams = []

    def respond(request):
        stream = RawStream([b"123456"])
        streams.append(stream)
        return httpx.Response(200, stream=stream)

    pool = ProxyPool(directory, client_factory=lambda url: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    service = service_for(tmp_path, respond, pool=pool)
    service.redis = directory
    token = USE_PROXY.set(True)
    try:
        with pytest.raises(DownloadLimitError):
            await service.request("GET", URL, allowed_domains=ALLOWED, max_retries=3,
                                  policy=ResponsePolicy(max_body_bytes=5, max_wire_bytes=10))
        assert len(streams) == 1 and streams[0].closed
        assert all(entry.failures == 0 and not entry.busy for entry in pool.entries.values())
        assert service.active["sina"] == 0 and service.buffer_budget.used == 0
    finally:
        USE_PROXY.reset(token)
        await service.close()
        await pool.close()


async def test_pdf_file_streaming_uses_chunk_budget_not_entire_file_reservation(tmp_path):
    payload = b"%PDF-1.7\n" + b"x" * (2 * 1024 * 1024)
    stream = RawStream([payload[i:i + CHUNK_BYTES] for i in range(0, len(payload), CHUNK_BYTES)])
    policy = FilePolicy(filename="report.pdf", signature=b"%PDF-", max_body_bytes=4 * 1024 * 1024,
                        max_wire_bytes=4 * 1024 * 1024, expected_sha256=hashlib.sha256(payload).hexdigest())
    service = service_for(tmp_path, lambda request: httpx.Response(200, stream=stream),
                          buffer_bytes=policy.reservation_bytes)
    try:
        result = await get(service, policy)
        target = tmp_path / "downloads" / "report.pdf"
        assert not result.content and target.read_bytes() == payload
        assert result.artifact["bytes"] == len(payload) and stream.closed
        assert service.buffer_budget.peak == 4 * CHUNK_BYTES and service.buffer_budget.used == 0
        assert list(target.parent.iterdir()) == [target] and not service.storage.active
    finally:
        await service.close()


@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_cancellation_at_file_commit_returns_published_artifact(
        tmp_path, monkeypatch, cancel_count):
    started, proceed = threading.Event(), threading.Event()
    original_commit = FileSink.commit

    def slow_commit(sink):
        started.set()
        assert proceed.wait(3)
        return original_commit(sink)

    monkeypatch.setattr(FileSink, "commit", slow_commit)
    payload = b"%PDF-1.7 complete"
    stream = RawStream([payload])
    policy = FilePolicy(filename="complete.pdf", signature=b"%PDF-",
                        max_body_bytes=100, max_wire_bytes=100)
    service = service_for(tmp_path, lambda request: httpx.Response(200, stream=stream))
    task = asyncio.create_task(get(service, policy))
    target = tmp_path / "downloads" / "complete.pdf"
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(.001)
        for _ in range(cancel_count):
            task.cancel()
            await asyncio.sleep(.01)
        assert not task.done() and not target.exists()
        proceed.set()
        result = await asyncio.wait_for(task, 2)
        assert result.artifact["path"] == str(target)
        assert target.read_bytes() == payload and stream.closed
        assert list(target.parent.iterdir()) == [target]
        assert not service.storage.active and service.buffer_budget.used == 0
    finally:
        proceed.set()
        await asyncio.gather(task, return_exceptions=True)
        await service.close()


async def test_file_validation_failure_preserves_diagnostic_not_a_partial_artifact(tmp_path):
    stream = RawStream([b"html error page"])
    records = ErrorRecorder()
    service = service_for(tmp_path, lambda request: httpx.Response(200, stream=stream), records=records)
    policy = FilePolicy(filename="wrong.pdf", signature=b"%PDF-", max_body_bytes=100, max_wire_bytes=100)
    try:
        with pytest.raises(DownloadLimitError, match="签名"):
            await get(service, policy)
        assert not list((tmp_path / "downloads").iterdir())
        assert not service.storage.active and service.buffer_budget.used == 0 and stream.closed
        assert len(records.errors) == 1
        assert records.errors[0]["raw_body"] == b"html error page"
        assert records.errors[0]["observed_bytes"] == len(b"html error page")
    finally:
        await service.close()


@pytest.mark.parametrize("method,status", [("HEAD", 200), ("GET", 204)])
async def test_head_and_no_content_never_download_body_or_publish_file(tmp_path, method, status):
    stream = RawStream([b"must not read"], block_after=0)
    service = service_for(tmp_path, lambda request: httpx.Response(status,
        headers={"Content-Length": "999999999"}, stream=stream))
    try:
        response = await service.request(method, URL, allowed_domains=ALLOWED,
            policy=FilePolicy(filename="empty.pdf", max_body_bytes=100, max_wire_bytes=100), max_retries=0)
        assert stream.closed and not stream.reads and not response.content and response.artifact is None
        assert not (tmp_path / "downloads").exists()
        response.close()
        assert service.buffer_budget.used == 0
    finally:
        await service.close()


@pytest.mark.parametrize("cancel_count", [1, 2])
async def test_cancellation_waits_for_actual_disk_write_before_cleanup(cancel_count):
    started, proceed = threading.Event(), threading.Event()
    steps = []

    class Sink:
        def write(self, chunk):
            steps.append("write started")
            started.set()
            assert proceed.wait(3)
            steps.append("write finished")

        def commit(self):
            raise AssertionError("cancelled download must not commit")

    sink = Sink()
    storage = SimpleNamespace(begin=lambda policy: sink,
                              end=lambda owned: steps.append("closed"))
    stream = RawStream([b"%PDF-data"])
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(200, stream=stream)))

    async def on_headers(response):
        pass

    task = asyncio.create_task(read_response(client, "GET", URL,
        policy=FilePolicy(filename="report.pdf"), storage=storage, on_headers=on_headers))
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(.001)
        for _ in range(cancel_count):
            task.cancel()
            await asyncio.sleep(.01)
        assert not task.done() and steps == ["write started"]
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert steps == ["write started", "write finished", "closed"] and stream.closed
    finally:
        proceed.set()
        await asyncio.gather(task, return_exceptions=True)
        await client.aclose()


async def test_byte_budget_validates_requests_and_release_is_idempotent():
    budget = ByteBudget(10)
    with pytest.raises(ValueError):
        await budget.reserve(11)
    assert budget.waiting == 0 and budget.used == 0
    first = budget.try_reserve(10)
    assert budget.try_reserve(1) is None
    first.release()
    first.release()
    assert budget.used == 0 and budget.peak == 10


async def test_file_admission_is_off_loop_and_repeated_cancel_cleans_created_sink(tmp_path, monkeypatch):
    started, proceed = threading.Event(), threading.Event()
    created, ended = [], []
    stream = RawStream([b"%PDF-data"])
    policy = FilePolicy(filename="admission.pdf", max_body_bytes=100, max_wire_bytes=100)
    service = service_for(tmp_path, lambda request: httpx.Response(200, stream=stream))
    begin, end = service.storage.begin, service.storage.end

    def blocked_begin(declaration):
        started.set()
        assert proceed.wait(3)
        sink = begin(declaration)
        created.append(sink)
        return sink

    def exact_end(sink):
        assert created == [sink]
        end(sink)
        ended.append(sink)

    monkeypatch.setattr(service.storage, "begin", blocked_begin)
    monkeypatch.setattr(service.storage, "end", exact_end)
    task = asyncio.create_task(get(service, policy))
    try:
        async with asyncio.timeout(2):
            while not started.is_set():
                await asyncio.sleep(.001)
        # Both callbacks execute while admission's real worker thread is blocked.
        pulses = []
        asyncio.get_running_loop().call_soon(pulses.append, "responsive")
        for _ in range(2):
            task.cancel()
            await asyncio.sleep(.01)
        assert pulses == ["responsive"] and not task.done()
        assert not created and not ended and service.buffer_budget.used == policy.reservation_bytes
        proceed.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert len(created) == 1 and ended == created
        assert not service.storage.active and not list((tmp_path / "downloads").iterdir())
        assert service.buffer_budget.used == 0 and service.storage.slots._value == 4
        assert stream.closed and stream.reads == 0
    finally:
        proceed.set()
        await asyncio.gather(task, return_exceptions=True)
        await service.close()


async def test_failed_external_reservation_stays_owned_until_ordered_consumer_releases(tmp_path):
    policy = ResponsePolicy(max_body_bytes=5, max_wire_bytes=10)
    streams = [RawStream([b"123456"]), RawStream([b"{}"])]
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, stream=streams[len(calls) - 1])

    service = service_for(tmp_path, respond, buffer_bytes=policy.reservation_bytes)
    lease = service.buffer_budget.try_reserve(policy.reservation_bytes)
    waiting = None
    try:
        with pytest.raises(DownloadLimitError) as caught:
            await get(service, policy, reservation=lease)
        assert caught.value.sample == b"123456"
        assert not lease.released and service.buffer_budget.used == policy.reservation_bytes
        assert streams[0].closed
        waiting = asyncio.create_task(get(service, policy))
        await asyncio.sleep(.01)
        assert not waiting.done() and len(calls) == 1 and service.buffer_budget.waiting == 1
        # This is the ordered consumer's point of processing the retained failure.
        lease.release()
        result = await asyncio.wait_for(waiting, 1)
        result.close()
        assert service.buffer_budget.used == 0 and service.buffer_budget.peak == policy.reservation_bytes
    finally:
        lease.release()
        if waiting and not waiting.done():
            waiting.cancel()
            await asyncio.gather(waiting, return_exceptions=True)
        await service.close()
