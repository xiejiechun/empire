from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.features.etf_fundamentals.collector import Collector, pack_cursor, unpack_cursor
from empire.features.etf_fundamentals.contract import CONTRACT, digest
from tests.prefetch_source import prefetch_http


@pytest.mark.parametrize("project", ["sse-etf-shares", "szse-etf-shares", "ttjj-etf-nav"])
async def test_complete_round_publishes_all_before_any_archive_wait(project):
    c = Collector(project)
    units = (
        [dict(code="510300.SH", start="2025-12-31", through="2026-01-01")]
        if c.source == "ttjj"
        else [dict(date="2026-11-12"), dict(date="2026-11-13")]
    )
    state = dict(revision=0, cursor={})
    pending, published = [], []
    c.http = prefetch_http()
    c.query = SimpleNamespace(plan=AsyncMock(return_value=dict(units=units, recent=[])))
    c.records = SimpleNamespace(sanitize_text=str, error=AsyncMock())

    async def publish(envelopes, **kw):
        assert not c.confirmation.page_status.await_count
        pending.extend(envelopes)
        published.extend(envelopes)
        state.update(revision=state["revision"] + 1, cursor=kw["cursor"])
        return dict(state)

    c.ingest = SimpleNamespace(
        checkpoint=AsyncMock(side_effect=lambda job: dict(state)),
        publish_page=AsyncMock(side_effect=publish),
        capacity=AsyncMock(return_value=dict(available=True)),
        advance_checkpoint=AsyncMock(),
    )

    async def read(unit, **kw):
        return [], datetime.now(UTC)

    c.fetch_unit = read

    async def confirm(*args):
        assert len(published) == 2
        pending.clear()
        return dict(status="complete", page=2)

    c.confirmation = SimpleNamespace(page_status=AsyncMock(side_effect=confirm))
    # Exercise the actual publication helper; capacity behavior is unrelated here.
    from empire.features.etf_fundamentals import collector

    async def send(ingest, stats, envelopes, **kw):
        return await publish(envelopes, **kw)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(collector, "publish_with_capacity", send)
        result = await c.execute()
    assert result["phase"] == "complete" and not pending
    assert c.ingest.advance_checkpoint.await_count == 1
    assert c.http.buffer_budget.used == 0


async def test_invalid_recent_empty_does_not_advance_checkpoint():
    c = Collector("sse-etf-shares")
    c.http = prefetch_http()
    c.query = SimpleNamespace(
        plan=AsyncMock(return_value=dict(units=[dict(date="2026-11-13")], recent=["2026-11-13"]))
    )
    c.ingest = SimpleNamespace(
        checkpoint=AsyncMock(return_value=dict(revision=0, cursor={})),
        advance_checkpoint=AsyncMock(),
    )
    c.records = SimpleNamespace(sanitize_text=str, error=AsyncMock())
    c.fetch_unit = AsyncMock(return_value=([], datetime.now(UTC)))
    with pytest.raises(ValueError, match="尚未发布"):
        await c.execute()
    c.ingest.advance_checkpoint.assert_not_awaited()
    assert c.http.buffer_budget.used == 0


async def test_fresh_resumes_unconfirmed_batch_before_replanning():
    c = Collector("sse-etf-shares")
    cursor = dict(
        contract=CONTRACT,
        scope=digest(dict(codes=None, start=None, end=None, sample_dates=None)),
        phase="awaiting_archive",
        batch="interrupted",
        units=[dict(date="2026-11-13")],
        recent=[],
        index=1,
        pages=1,
        collected=1,
    )
    c.ingest = SimpleNamespace(
        checkpoint=AsyncMock(return_value=dict(revision=7, cursor=pack_cursor(cursor))),
        advance_checkpoint=AsyncMock(),
    )
    c.query = SimpleNamespace(plan=AsyncMock())
    c.confirmation = SimpleNamespace(
        page_status=AsyncMock(return_value=dict(status="complete", page=1))
    )
    c.records = SimpleNamespace(sanitize_text=str, error=AsyncMock())
    result = await c.execute(fresh=True, baseline_revision=7)
    assert result["batch"] == "interrupted" and result["phase"] == "complete"
    c.query.plan.assert_not_awaited()
    c.confirmation.page_status.assert_awaited_once()
    c.ingest.advance_checkpoint.assert_awaited_once()


def test_full_catalog_plan_fits_shared_checkpoint_and_roundtrips():
    import json

    units = [dict(code=f"{i:06d}.SH", start="2026-11-03", through="2026-11-16") for i in range(5000)]
    cursor = dict(units=units, index=0, pages=0, phase="fetch")
    packed = pack_cursor(cursor)
    assert len(json.dumps(packed).encode()) < 16384
    assert unpack_cursor(packed) == cursor
    with pytest.raises(ValueError):
        unpack_cursor({**packed, "units": packed["units"] + "junk"})


async def test_years_publish_individually_and_resume_only_unfinished_years():
    import asyncio

    c = Collector("ttjj-etf-nav")
    c.http = prefetch_http()
    c.query = SimpleNamespace(plan=AsyncMock(return_value=dict(
        units=[dict(code="510300.SH", start="2004-12-30", through="2026-11-13")], recent=[])))
    state, messages, requests = dict(revision=0, cursor={}), [], []

    async def publish(envelopes, **kw):
        assert len(envelopes) == 1
        assert not c.confirmation.page_status.await_count
        if len(messages) == 1 and len(requests) == 1:
            raise asyncio.CancelledError
        messages.extend(envelopes)
        state.update(revision=state["revision"] + 1, cursor=kw["cursor"])
        return dict(state)

    async def fetch(unit, **kw):
        requests.append(unit)
        return [], datetime.now(UTC)

    c.fetch_unit = fetch
    c.ingest = SimpleNamespace(checkpoint=AsyncMock(side_effect=lambda _: dict(state)),
        publish_page=AsyncMock(side_effect=publish), advance_checkpoint=AsyncMock())
    c.confirmation = SimpleNamespace(page_status=AsyncMock(return_value=dict(status="complete")))
    c.records = SimpleNamespace(sanitize_text=str, add_error=AsyncMock())
    from empire.features.etf_fundamentals import collector

    async def send(ingest, stats, envelopes, **kw):
        return await publish(envelopes, **kw)

    with pytest.MonkeyPatch.context() as m:
        m.setattr(collector, "publish_with_capacity", send)
        with pytest.raises(asyncio.CancelledError):
            await c.execute()
        partial = unpack_cursor(state["cursor"])
        assert partial["index"] == 0 and partial["next_year"] == 2005 and partial["pages"] == 1
        result = await c.execute()
    assert requests[1]["start"] == "2005-01-01"
    assert result["phase"] == "complete" and result["pages"] == 23
    assert [m.raw_payload["start"][:4] for m in messages] == [str(y) for y in range(2004, 2027)]
    c.query.plan.assert_awaited_once()
    c.confirmation.page_status.assert_awaited_once()
