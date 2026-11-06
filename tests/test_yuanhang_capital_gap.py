"""Initial-capital source availability cannot freeze unrelated securities or fake coverage."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from empire.contracts.collector import CollectionSourceGap
from empire.core.time import CHINA
from empire.features.yuanhang import collector as module
from empire.features.yuanhang.availability import DeferredSecurity
from empire.plugins.infra.routing import USE_PROXY
from tests.test_yuanhang_checkpoint import harness

CODES = ['000001.SZ', '000002.SZ', '000003.SZ']


def gap(code):
    return DeferredSecurity(code, '2026-11-06', '2026-11-06', 'partial_total_circulating',
                            'deferred_initial_capital', '2026-11-06', 'node')


def setup(monkeypatch):
    c = harness(monkeypatch, CODES, financial=True)
    c.query.collection_scope = AsyncMock(return_value=(CODES, '2026-11-06'))
    complete = c.fetch.return_value
    c.fetch.side_effect = lambda unit: gap(unit[0]) if unit[0] == CODES[1] else complete
    return c, complete


async def test_gap_confirms_other_units_and_retries_only_missing_then_clears_evidence(monkeypatch):
    c, complete = setup(monkeypatch)
    token = USE_PROXY.set(True)
    try:
        for run in range(2):
            c.fetch.reset_mock()
            with pytest.raises(CollectionSourceGap, match=CODES[1]):
                await c.execute(baseline_revision=await c.checkpoint_revision())
            assert [call.args[0][0] for call in c.fetch.await_args_list] == (CODES if run == 0 else [CODES[1]])
            assert c.ingest.state['cursor']['phase'] == 'source_gap'
            assert c.stats['status'] == 'source_gap' and c.stats['source_gap_units'] == 1
            assert len(c.ingest.messages) == 2
            module.record_error_safely.assert_not_awaited()
        c.fetch.reset_mock()
        c.fetch.side_effect = None
        c.fetch.return_value = complete
        result = await c.execute(baseline_revision=await c.checkpoint_revision())
        assert [call.args[0][0] for call in c.fetch.await_args_list] == [CODES[1]]
        assert result['phase'] == 'complete' and result['deferred'] == {}
        assert c.stats['source_gap_units'] == 0 and len(c.ingest.messages) == 3
    finally:
        USE_PROXY.reset(token)


async def test_gap_retry_interruption_retains_published_plan_and_unresolved_suffix(monkeypatch):
    c, complete = setup(monkeypatch)
    token = USE_PROXY.set(True)
    try:
        with pytest.raises(CollectionSourceGap):
            await c.execute()
        # The recovered unit is atomically published, then the position CAS fails.
        advance = c.ingest.advance_checkpoint
        async def interrupt(**kwargs):
            if kwargs['cursor'].get('retry_deferred') and kwargs['cursor']['next_index'] == 2:
                raise ValueError('interrupted position CAS')
            return await advance(**kwargs)
        c.ingest.advance_checkpoint = interrupt
        c.fetch.side_effect = None
        c.fetch.return_value = complete
        with pytest.raises(ValueError, match='interrupted position'):
            await c.execute(baseline_revision=await c.checkpoint_revision())
        assert c.ingest.state['cursor']['current_plan']['mode'] == 'financial'
        c.ingest.advance_checkpoint = advance
        c.fetch.reset_mock()
        result = await c.execute(baseline_revision=await c.checkpoint_revision())
        assert result['phase'] == 'complete' and result['deferred'] == {}
        assert c.fetch.await_count == 1 and len(c.ingest.messages) == 3
    finally:
        USE_PROXY.reset(token)


async def test_source_gap_waits_for_archive_and_new_day_uses_normal_daily_scope(monkeypatch):
    c, _ = setup(monkeypatch)
    token = USE_PROXY.set(True)
    try:
        module.wait_for_archive.side_effect = ValueError('archive unavailable')
        with pytest.raises(ValueError, match='archive unavailable'):
            await c.execute()
        assert c.ingest.state['cursor']['phase'] == 'awaiting_archive'
        module.wait_for_archive.side_effect = None
        with pytest.raises(CollectionSourceGap):
            await c.execute(baseline_revision=await c.checkpoint_revision())
        c.ingest.state['cursor']['run_date'] = (datetime.now(CHINA).date() - timedelta(days=1)).isoformat()
        c.fetch.reset_mock()
        with pytest.raises(CollectionSourceGap):
            await c.execute(baseline_revision=await c.checkpoint_revision())
        assert [call.args[0][0] for call in c.fetch.await_args_list] == CODES
    finally:
        USE_PROXY.reset(token)


async def test_gap_scope_change_cannot_discard_pending_evidence(monkeypatch):
    c, _ = setup(monkeypatch)
    token = USE_PROXY.set(True)
    try:
        with pytest.raises(CollectionSourceGap):
            await c.execute()
        before = await c.ingest.checkpoint(c.job_key)
        c.query.collection_scope.return_value = (CODES[1:], '2026-11-06')
        with pytest.raises(ValueError, match='股票范围已改变'):
            await c.execute(baseline_revision=await c.checkpoint_revision())
        assert await c.ingest.checkpoint(c.job_key) == before
    finally:
        USE_PROXY.reset(token)
