"""The observed -1009 query timeout shares the transport retry budget."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.hot_list.collector import HotListCollector
from empire.features.hot_list.source import parse_detail, transient_query_timeout
from empire.plugins.infra.http import HttpService
from tests.test_http import ErrorRecorder, MemoryPermits
from tests.test_tdx_hot_list import CODE, DATE, detail, directory

TIMEOUT = {"ErrorCode": -1009, "ErrorInfo": "cache语句执行超时", "hitCache": False}
GROUPS = {"tdx": {"domains": ["tdx.com.cn"], "min_interval_ms": 1, "total_interval_ms": 1}}


@pytest.mark.parametrize("body,expected", [
    (TIMEOUT, True),
    ({**TIMEOUT, "ResultSets": []}, True),
    ({**TIMEOUT, "ErrorCode": "-1009"}, False),
    ({**TIMEOUT, "ErrorCode": -1005}, False),
    ({**TIMEOUT, "ErrorInfo": "unknown"}, False),
    ({**TIMEOUT, "ResultSets": [{}]}, False),
    ([], False), (directory(), False),
])
def test_only_observed_timeout_is_retryable(body, expected):
    assert transient_query_timeout(httpx.Response(200, json=body)) is expected
    assert not transient_query_timeout(httpx.Response(200, content=b"{broken"))


@pytest.mark.parametrize("requested", [None, DATE])
@pytest.mark.parametrize("sequence,budget,success", [
    (["valid"], 10, True),
    (["timeout", "valid"], 10, True),
    (["503", "timeout", "valid"], 2, True),
    (["503", "timeout", "valid"], 1, False),
    (["timeout"] * 11, 10, False),
    (["timeout"], 0, False),
    (["unknown", "valid"], 10, False),
    (["invalid", "valid"], 10, False),
    (["structure", "valid"], 10, False),
])
async def test_timeout_uses_shared_budget(requested, sequence, budget, success, monkeypatch):
    responses, attempts = [], []
    records = ErrorRecorder()
    records.sanitize_text = str

    def respond(request):
        kind = sequence[len(attempts)]
        attempts.append(json.loads(request.content)["Params"])
        body = (directory() if requested is None else detail()) if kind == "valid" else (
            TIMEOUT if kind == "timeout" else {**TIMEOUT, "ErrorCode": -1005}
            if kind == "unknown" else {"ErrorCode": 0, "ResultSets": []})
        response = (httpx.Response(200, content=b"{broken") if kind == "invalid" else
                    httpx.Response(503 if kind == "503" else 200, json=body))
        responses.append(response)
        return response

    service = HttpService(MemoryPermits(), "test", GROUPS, records=records,
                          transport=httpx.MockTransport(respond))
    c = HotListCollector()
    c.http, c.records, c.request_retries = service, records, budget
    c.ingest = SimpleNamespace(ensure_capacity=AsyncMock())
    monkeypatch.setattr("empire.plugins.infra.http.retry_delay", lambda attempt: 0)
    read = None
    try:
        read = await c.fetch((CODE, requested, DATE))
        if success:
            value, _ = await read.consume()
            assert value == ([DATE] if requested is None else
                             parse_detail(detail()))
            assert len(attempts) == len(sequence)
        else:
            with pytest.raises(ValueError):
                await read.consume()
            assert len(attempts) == (1 if sequence[0] in ("unknown", "invalid", "structure") else budget + 1)
            if sequence[0] not in ("unknown", "invalid", "structure"):
                assert "cache语句执行超时" in str(records.errors[-1]["error"])
                assert records.errors[-1]["metadata"]["params"] == attempts[-1]
        assert all(p == attempts[0] for p in attempts)
    finally:
        if read is not None:
            read.close()
        assert all(r.is_closed for r in responses)
        assert service.buffer_budget.used == 0 and not service.responses
        await service.close()


async def test_cancel_query_retry_releases_resources(monkeypatch):
    reached = asyncio.Event()
    original_sleep = asyncio.sleep

    async def sleep(delay):
        if delay == 0.123:
            reached.set()
            await asyncio.Event().wait()
        else:
            await original_sleep(delay)

    monkeypatch.setattr(asyncio, "sleep", sleep)
    monkeypatch.setattr("empire.plugins.infra.http.retry_delay", lambda attempt: 0.123)
    service = HttpService(MemoryPermits(), "test", GROUPS, records=ErrorRecorder(),
                          transport=httpx.MockTransport(lambda request: httpx.Response(200, json=TIMEOUT)))
    c = HotListCollector()
    c.http, c.ingest = service, SimpleNamespace(ensure_capacity=AsyncMock())
    task = asyncio.create_task(c.fetch((CODE, None, DATE)))
    try:
        await asyncio.wait_for(reached.wait(), 3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert service.buffer_budget.used == 0 and not service.responses
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await service.close()
