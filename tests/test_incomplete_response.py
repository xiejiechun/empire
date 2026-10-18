"""Incomplete HTTP bodies retry without weakening limits or accepting prefixes."""
import gzip
import zlib

import httpx
import pytest
from test_download_resources import ALLOWED, URL, RawStream, service_for
from test_http import ErrorRecorder

from empire.contracts.download import CHUNK_BYTES, FilePolicy, ResponsePolicy
from empire.plugins.infra.response_reader import DownloadIncompleteError, DownloadLimitError


@pytest.mark.parametrize('encoding', ['gzip', 'deflate', 'identity'])
async def test_incomplete_first_response_retries_and_only_returns_complete_body(tmp_path, encoding):
    payload = b'{"financial":' + b'1' * 146500 + b'}'
    encoded = {'gzip': gzip.compress(payload), 'deflate': zlib.compress(payload), 'identity': payload}[encoding]
    streams = []
    records = ErrorRecorder()

    def respond(request):
        stream = RawStream([encoded[:-3] if not streams else encoded])
        streams.append(stream)
        return httpx.Response(200, headers={'Content-Encoding': encoding,
                                           'Content-Length': str(len(encoded))}, stream=stream)

    service = service_for(tmp_path, respond, records=records)
    try:
        response = await service.request('GET', URL, allowed_domains=ALLOWED, project_id='ths-cashflow',
            max_retries=2, policy=ResponsePolicy(max_body_bytes=200000, max_wire_bytes=200000))
        assert response.content == payload and len(streams) == 2
        assert all(s.closed for s in streams)
        assert len(records.errors) == 1
        record = records.errors[0]
        assert record['status_code'] == 200 and record['raw_body_complete'] is False
        assert record['metadata']['attempt'] == 1
        response.close()
        assert not service.responses and service.buffer_budget.used == 0
    finally:
        await service.close()


async def test_incomplete_retry_exhaustion_is_bounded_and_keeps_attempt_diagnostics(tmp_path):
    encoded = gzip.compress(b'partial')[:-2]
    streams = []
    records = ErrorRecorder()

    def respond(request):
        stream = RawStream([encoded])
        streams.append(stream)
        return httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=stream)

    service = service_for(tmp_path, respond, records=records)
    try:
        with pytest.raises(DownloadIncompleteError, match='未完整结束'):
            await service.request('GET', URL, allowed_domains=ALLOWED, project_id='ths-cashflow', max_retries=2,
                policy=ResponsePolicy(max_body_bytes=1000, max_wire_bytes=1000))
        assert len(streams) == 3 and all(s.closed for s in streams)
        assert [r['metadata']['attempt'] for r in records.errors] == [1, 2, 3]
        assert all(r['raw_body_complete'] is False and r['status_code'] == 200 for r in records.errors)
        assert not service.responses and service.buffer_budget.used == 0
    finally:
        await service.close()


@pytest.mark.parametrize('encoded', [b'broken-gzip', gzip.compress(b'a') + gzip.compress(b'b')])
async def test_invalid_compression_is_not_retried(tmp_path, encoded):
    streams = []

    def respond(request):
        stream = RawStream([encoded])
        streams.append(stream)
        return httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=stream)

    service = service_for(tmp_path, respond)
    try:
        with pytest.raises(DownloadLimitError):
            await service.request('GET', URL, allowed_domains=ALLOWED, project_id='ths-cashflow', max_retries=2,
                policy=ResponsePolicy(max_body_bytes=1000, max_wire_bytes=1000))
        assert len(streams) == 1 and streams[0].closed and service.buffer_budget.used == 0
    finally:
        await service.close()


@pytest.mark.parametrize('size', [CHUNK_BYTES, CHUNK_BYTES * 2, CHUNK_BYTES + 146523])
async def test_complete_large_gzip_is_not_misclassified_as_truncated(tmp_path, size):
    body = b'a' * size
    encoded = gzip.compress(body)
    streams = []

    def respond(request):
        stream = RawStream([encoded[i:i+3] for i in range(0, len(encoded), 3)])
        streams.append(stream)
        return httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=stream)

    service = service_for(tmp_path, respond)
    try:
        response = await service.request('GET', URL, allowed_domains=ALLOWED, project_id='ths-cashflow',
            max_retries=2, policy=ResponsePolicy(max_body_bytes=size, max_wire_bytes=size))
        assert response.content == body and len(streams) == 1
        response.close()
        assert service.buffer_budget.used == 0
    finally:
        await service.close()


@pytest.mark.parametrize("retries", [2, 100])
async def test_total_deadline_still_bounds_incomplete_backoff(tmp_path, retries):
    streams = []

    def respond(request):
        stream = RawStream([gzip.compress(b'abc')[:-2]])
        streams.append(stream)
        return httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=stream)

    service = service_for(tmp_path, respond)
    try:
        with pytest.raises(TimeoutError):
            await service.request('GET', URL, allowed_domains=ALLOWED, project_id='ths-cashflow',
                max_retries=retries, total_timeout=.05, policy=ResponsePolicy(max_body_bytes=1000, max_wire_bytes=1000))
        assert len(streams) == 1 and streams[0].closed
        assert not service.inflight and service.buffer_budget.used == 0
    finally:
        await service.close()


async def test_file_retry_removes_partial_file_before_publishing_complete_artifact(tmp_path):
    payload = b'%PDF-1.7 complete'
    encoded = gzip.compress(payload)
    streams = []

    def respond(request):
        if streams:
            assert not list((tmp_path / 'downloads').iterdir())
        stream = RawStream([encoded if streams else encoded[:-2]])
        streams.append(stream)
        return httpx.Response(200, headers={'Content-Encoding': 'gzip'}, stream=stream)

    service = service_for(tmp_path, respond)
    try:
        response = await service.request('GET', URL, allowed_domains=ALLOWED, project_id='test-file',
            max_retries=2, policy=FilePolicy(filename='complete.pdf', signature=b'%PDF-',
                                           max_body_bytes=1000, max_wire_bytes=1000))
        target = tmp_path / 'downloads' / 'complete.pdf'
        assert target.read_bytes() == payload
        assert list(target.parent.iterdir()) == [target]
        assert len(streams) == 2 and all(s.closed for s in streams)
        assert not service.storage.active and service.buffer_budget.used == 0
        response.close()
    finally:
        await service.close()
