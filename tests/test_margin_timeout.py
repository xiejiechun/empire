"""The observed -1009 query timeout shares the transport retry budget."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.margin.collector import MarginCollector
from empire.features.margin.source import parse, transient_query_timeout
from empire.plugins.infra.http import HttpService
from tests.test_http import ErrorRecorder, MemoryPermits
from tests.test_tdx_margin import response as valid_response

CODE, DATE = "000001.SZ", "2026-11-12"

TIMEOUT = {"ErrorCode": -1009, "ErrorInfo": "cache语句执行超时", "hitCache": False}
GROUPS = {"tdx": {"domains": ["tdx.com.cn"], "min_interval_ms": 1, "total_interval_ms": 1}}


@pytest.mark.parametrize("body,expected", [
    (TIMEOUT, True),
    ({**TIMEOUT, "ResultSets": []}, True),
    ({**TIMEOUT, "ErrorCode": "-1009"}, False),
    ({**TIMEOUT, "ErrorCode": -1005}, False),
    ({**TIMEOUT, "ErrorInfo": "unknown"}, False),
    ({**TIMEOUT, "ResultSets": [{}]}, False),
    ([], False), (valid_response(), False),
])
def test_only_observed_timeout_is_retryable(body, expected):
    assert transient_query_timeout(httpx.Response(200, json=body)) is expected
    assert not transient_query_timeout(httpx.Response(200, content=b"{broken"))


@pytest.mark.parametrize("code", ["000001.SZ", "688256.SH", "920001.BJ"])
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
async def test_timeout_uses_shared_budget(code, sequence, budget, success, monkeypatch):
    responses, attempts = [], []
    records = ErrorRecorder()
    records.sanitize_text = str

    def respond(request):
        kind = sequence[len(attempts)]
        attempts.append(json.loads(request.content)["Params"])
        body = valid_response() if kind == "valid" else (
            TIMEOUT if kind == "timeout" else {**TIMEOUT, "ErrorCode": -1005}
            if kind == "unknown" else {"ErrorCode": 0, "ResultSets": []})
        response = (httpx.Response(200, content=b"{broken") if kind == "invalid" else
                    httpx.Response(503 if kind == "503" else 200, json=body))
        responses.append(response)
        return response

    service = HttpService(MemoryPermits(), "test", GROUPS, records=records,
                          transport=httpx.MockTransport(respond))
    c = MarginCollector()
    c.http, c.records, c.request_retries = service, records, budget
    c.ingest = SimpleNamespace(ensure_capacity=AsyncMock())
    monkeypatch.setattr("empire.plugins.infra.http.retry_delay", lambda attempt: 0)
    read = None
    try:
        read = await c.fetch((code, DATE))
        if success:
            value, _ = await read.consume()
            assert value == parse(valid_response(), DATE)
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
    c = MarginCollector()
    c.http, c.ingest = service, SimpleNamespace(ensure_capacity=AsyncMock())
    task = asyncio.create_task(c.fetch((CODE, DATE)))
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


async def test_exhausted_timeout_preserves_cursor_and_resume(monkeypatch):
    from tests.test_margin_lifecycle import collector

    c, state, published = collector()
    attempts = []
    fail = True

    def respond(request):
        code = json.loads(request.content)["Params"][2]
        attempts.append(code)
        return httpx.Response(200, json=TIMEOUT if fail and code == "688256" else valid_response())

    records = ErrorRecorder()
    records.sanitize_text = str
    service = HttpService(MemoryPermits(), "test", GROUPS, records=records,
                          transport=httpx.MockTransport(respond))
    c.http, c.records, c.request_retries = service, records, 1
    monkeypatch.setattr("empire.plugins.infra.http.retry_delay", lambda attempt: 0)
    try:
        with pytest.raises(ValueError, match="-1009.*cache语句执行超时"):
            await c.execute()
        assert state["cursor"]["index"] == 1 and len(published) == 1
        assert attempts.count("688256") == 2
        batch = state["cursor"]["batch_id"]
        assert not c.confirmation.page_status.called
        before = len(attempts)
        fail = False
        await c.execute(baseline_revision=state["revision"])
        assert attempts[before:] == ["688256"]
        assert state["cursor"]["phase"] == "complete"
        assert state["cursor"]["batch_id"] == batch
        assert len(published) == 2
        assert service.buffer_budget.used == 0 and not service.responses
    finally:
        await service.close()
