from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.contracts.data import BackpressureError, BatchReservationError, make_envelope
from empire.plugins.collectors.support import (
    publish_with_capacity,
    record_error_safely,
    wait_for_archive,
    wait_for_capacity,
)


class RecoveringIngest:
    def __init__(self):
        self.capacity_calls = 0
        self.publish_calls = 0

    async def ensure_capacity(self, incoming=1, reservation=None):
        self.capacity_calls += 1
        if self.capacity_calls == 1:
            raise BackpressureError("busy")

    async def publish_page(self, events, **kwargs):
        self.publish_calls += 1
        if self.publish_calls == 1:
            raise BackpressureError("race")
        return {"revision": 1, "cursor": kwargs["cursor"]}


async def test_capacity_wait_and_publish_share_recoverable_pause_contract():
    ingest = RecoveringIngest()
    stats = {}
    await wait_for_capacity(ingest, stats, retry_seconds=0)
    assert stats == {"status": "collecting", "error": ""}

    event = make_envelope(
        source="test", dataset="metric.page", business_key="1", job_key="job",
        run_id="run", batch_id="batch", payload={"value": 1},
    )
    result = await publish_with_capacity(
        ingest, stats, [event], job_key="job", expected_revision=0,
        cursor={"page": 1}, retry_seconds=0,
    )
    assert result == {"revision": 1, "cursor": {"page": 1}}
    assert ingest.publish_calls == 2


async def test_invalid_batch_reservation_is_not_retried_forever():
    ingest = SimpleNamespace(
        ensure_capacity=AsyncMock(side_effect=BatchReservationError("expired")))
    with pytest.raises(BatchReservationError, match="expired"):
        await wait_for_capacity(ingest, {}, retry_seconds=0)
    ingest.ensure_capacity.assert_awaited_once()


async def test_archive_wait_uses_common_complete_and_invalid_contract():
    statuses = iter([None, {"status": "complete", "page": 2}])

    async def complete():
        return next(statuses)

    assert await wait_for_archive(complete, retry_seconds=0) == {
        "status": "complete", "page": 2,
    }

    async def invalid():
        return {"status": "invalid", "error_text": "bad page"}

    with pytest.raises(ValueError, match="bad page"):
        await wait_for_archive(invalid, retry_seconds=0)


async def test_diagnostic_failure_never_hides_original_error():
    records = SimpleNamespace(add_error=AsyncMock(side_effect=RuntimeError("redis unavailable")))
    stats = {}
    original = ValueError("source invalid")
    assert not await record_error_safely(
        records, stats, "project", original, stage="parse",
        unavailable_message="diagnostic unavailable", fields={"status_code": 500},
    )
    assert stats["diagnostic_error"] == "diagnostic unavailable"
    records.add_error.assert_awaited_once_with(
        "project", stage="parse", error="source invalid", status_code=500)

    original.diagnostic_recorded = True
    assert not await record_error_safely(
        records, stats, "project", original, stage="parse",
        unavailable_message="diagnostic unavailable",
    )
    assert records.add_error.await_count == 1
