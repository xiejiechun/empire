"""Source opt-in uses the shared HTTP budget before parsing a complete matrix."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.features.financial_statements.collector import ThsStatementCollector
from empire.features.financial_statements.contract import KINDS, parse
from empire.plugins.infra.http import HttpService
from empire.plugins.infra.response_reader import DownloadIncompleteError
from tests.test_http import ErrorRecorder, MemoryPermits
from tests.test_ths_statements import STOCK, source

GROUPS = {'ths': {'domains': ['10jqka.com.cn'], 'min_interval_ms': 1, 'total_interval_ms': 1}}


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('sequence,budget,success', [
    (['valid'], 30, True),
    (['empty', 'valid'], 30, True),
    (['502', 'empty', 'valid'], 2, True),
    (['502', 'empty', 'valid'], 1, False),
    (['empty'] * 31, 30, False),
    (['empty'], 0, False),
    (['invalid', 'valid'], 30, False),
    (['matrix', 'valid'], 30, False),
])
async def test_empty_body_uses_source_budget(kind, sequence, budget, success, monkeypatch):
    attempts, responses = [], []
    records = ErrorRecorder()
    records.sanitize_text = str

    def respond(request):
        value = sequence[len(attempts)]
        attempts.append(value)
        response = (httpx.Response(200, json=source(kind)) if value == 'valid' else
                    httpx.Response(200, json={'flashData': '{}'}) if value == 'matrix' else
                    httpx.Response(502 if value == '502' else 200,
                                   content=b'not json' if value == 'invalid' else b''))
        responses.append(response)
        return response

    service = HttpService(MemoryPermits(), 'test', GROUPS, records=records,
                          transport=httpx.MockTransport(respond))
    collector = ThsStatementCollector(kind)
    collector.http, collector.records = service, records
    collector.ingest = SimpleNamespace(ensure_capacity=AsyncMock())
    collector.request_retries = budget
    monkeypatch.setattr('empire.plugins.infra.http.retry_delay', lambda attempt: 0)
    try:
        if success:
            rows, _, _ = await collector.fetch(STOCK)
            assert rows == parse(kind, source(kind), STOCK)
            assert len(attempts) == len(sequence)
        else:
            expected = ValueError if sequence[0] in ('invalid', 'matrix') else DownloadIncompleteError
            with pytest.raises(expected):
                await collector.fetch(STOCK)
            assert len(attempts) == (1 if sequence[0] in ('invalid', 'matrix') else budget + 1)
        assert all(response.is_closed for response in responses)
        assert not service.responses and service.buffer_budget.used == 0
        assert all(row['project_id'] == collector.project_id for row in records.errors)
        if not success and sequence[0] not in ('invalid', 'matrix'):
            assert len(records.errors) == budget + 1
            assert '空正文' in str(records.errors[-1]['error'])
    finally:
        await service.close()


@pytest.mark.parametrize('kind', KINDS)
async def test_cancel_empty_retry_releases_resources(kind, monkeypatch):
    reached = asyncio.Event()
    records = ErrorRecorder()
    async def pause(delay):
        reached.set()
        await asyncio.Event().wait()
    monkeypatch.setattr('empire.plugins.infra.http.retry_delay', lambda attempt: 0.123)
    original_sleep = asyncio.sleep
    async def sleep(delay):
        if delay == 0.123:
            await pause(delay)
        else:
            await original_sleep(delay)
    monkeypatch.setattr(asyncio, 'sleep', sleep)
    service = HttpService(MemoryPermits(), 'test', GROUPS, records=records,
                          transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b'')))
    collector = ThsStatementCollector(kind)
    collector.http, collector.records = service, records
    collector.ingest = SimpleNamespace(ensure_capacity=AsyncMock())
    task = asyncio.create_task(collector.fetch(STOCK))
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
