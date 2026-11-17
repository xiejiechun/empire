"""Known source timeout recovery through the downloader, Redis, archive and SQL."""
import json

import httpx
import pytest
from sqlalchemy import event

from empire.features.margin.contract import JOB
from empire.features.margin.source import parse
from empire.plugins.infra.http import HttpService
from tests.integration import test_margin_archive as margin_archive
from tests.test_http import MemoryPermits
from tests.test_margin_timeout import GROUPS, TIMEOUT
from tests.test_tdx_margin import response

pytestmark = margin_archive.pytestmark
pipeline, collect = margin_archive.pipeline, margin_archive.collect


async def test_timeout_recovery_roundtrip_and_exhaustion_preserve_sql(pipeline, monkeypatch):
    manager, c, q, store = pipeline
    attempts, responses = [], []
    sequence = ["503", "timeout", "valid"]

    def respond(request):
        attempts.append(json.loads(request.content)["Params"])
        kind = sequence.pop(0)
        value = httpx.Response(503 if kind == "503" else 200,
                               json=response() if kind == "valid" else TIMEOUT)
        responses.append(value)
        return value

    service = HttpService(MemoryPermits(), "test", GROUPS, records=c.records,
                          transport=httpx.MockTransport(respond))
    c.http, c.request_retries = service, 2
    monkeypatch.setattr("empire.plugins.infra.http.retry_delay", lambda attempt: 0)
    dml = []

    def track(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) and "margin_" in statement:
            dml.append(statement)

    try:
        await collect(c)
        expected = parse(response(), "2026-11-12")
        assert await q.history("688256.SH") == expected
        assert len(attempts) == 3 and all(p == attempts[0] for p in attempts)
        assert await store.client.xlen(store.stream) == 0
        state = await c.ingest.checkpoint(JOB)
        event.listen(q.mysql.engine, "before_cursor_execute", track)
        event.listen(q.mysql.archive_engine, "before_cursor_execute", track)
        try:
            sequence[:] = ["timeout"] * 3
            with pytest.raises(ValueError, match="-1009.*cache语句执行超时"):
                await collect(c)
            assert await c.ingest.checkpoint(JOB) == state
            assert await q.history("688256.SH") == expected
            assert not dml and await store.client.xlen(store.stream) == 0
            sequence[:] = ["timeout", "valid"]
            await collect(c)
            assert not dml
            assert await q.history("688256.SH") == expected
            assert await store.client.xlen(store.stream) == 0
        finally:
            event.remove(q.mysql.engine, "before_cursor_execute", track)
            event.remove(q.mysql.archive_engine, "before_cursor_execute", track)
        assert service.buffer_budget.used == 0 and not service.responses
        assert all(r.is_closed for r in responses)
    finally:
        await service.close()
