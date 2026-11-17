"""Maintenance cost and proof-age regressions for the nine TDX changes."""
import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.features.capital_actions.dataset import CapitalDataset
from empire.features.capital_actions.dividends_collector import TdxDividendsCollector
from empire.features.performance.dataset import PerformanceDataset
from empire.plugins.infra.tdx_maintenance import RecoveryStage, needs_review, proofs_fresh
from tests.test_capital_lifecycle import configured
from tests.test_tdx_performance_lifecycle import collector


def archived(mapping, events):
    state = {}
    for event in events:
        data = mapping.normalize(event)
        state = mapping.archive_state(event, data, {'confirmed': [data['unit']]}, state)
    return state


@pytest.mark.parametrize('kind', ['earnings_report', 'earnings_quick', 'earnings_forecast', 'earnings_disclosure', 'holder_count'])
async def test_unchanged_round_only_reads_directory_and_publishes_manifest(kind, monkeypatch):
    c, checkpoint = collector(kind, monkeypatch)
    first = await c.execute()
    events = [call.args[0][0] for call in c.ingest.publish_page.call_args_list]
    proof = archived(PerformanceDataset(kind), events)
    c.query.state.return_value = proof
    c.http.request.reset_mock()
    c.ingest.publish_page.reset_mock()
    second = await c.execute(baseline_revision=checkpoint['revision'])
    assert c.http.request.await_count == 1
    assert c.ingest.publish_page.await_count == 1
    assert second['rolling'] == first['rolling']
    assert second['collected'] == first['collected']
    assert c.query.state.return_value == proof  # Reusing does not stamp old units as new.


async def test_missing_market_forces_one_complete_response(monkeypatch):
    c, checkpoint = collector('earnings_report', monkeypatch)
    await c.execute()
    state = archived(PerformanceDataset(c.kind), [call.args[0][0] for call in c.ingest.publish_page.call_args_list])
    del state['units'][next(iter(state['units']))]
    c.query.state.return_value = state
    c.http.request.reset_mock()
    await c.execute(baseline_revision=checkpoint['revision'])
    assert c.http.request.await_count == 2


async def test_compression_runs_once_per_market(monkeypatch):
    from unittest.mock import Mock

    from empire.features.performance import collector as module
    c, _ = collector('earnings_report', monkeypatch)
    packed = Mock(wraps=module.pack)
    monkeypatch.setattr(module, 'pack', packed)
    await c.execute()
    assert packed.call_count == 3  # Budget probe and final message share the same payload.


async def test_listing_retry_reuses_validated_days(monkeypatch):
    import json

    from tests.test_listing_status import collector as listing_collector
    c = listing_collector()
    c.query.plan.return_value = ['1991-01']
    original = c.http.request.side_effect

    def fail_second(*args, **kwargs):
        if json.loads(kwargs['content'])['Params'][2] == '1991-01-02':
            raise RuntimeError('second day failed')
        return original(*args, **kwargs)

    c.http.request.side_effect = fail_second
    with pytest.raises(RuntimeError, match='second day failed'):
        await c.execute()
    assert not c.ingest.events
    c.http.request.side_effect = original
    c.http.request.reset_mock()
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.http.request.await_count == 1
    assert c.ingest.events[0].raw_payload['rows']
    assert not c.recovery.units


async def test_dividend_unchanged_periods_do_not_download_or_requeue_securities(monkeypatch):
    monkeypatch.setattr('empire.features.capital_actions.dividend_history.report_periods',
                        AsyncMock(return_value=['2025-12-31']))
    c, _ = configured(TdxDividendsCollector)
    await c.execute()
    state = archived(CapitalDataset('dividends'), c.ingest.events)
    units = {e.raw_payload['unit']: e.raw_payload['rows'] for e in c.ingest.events
             if e.raw_payload['unit'] != 'manifest'}
    c.query.dividend_maintenance = AsyncMock(return_value=(state, copy.deepcopy(units)))
    c.http.request.reset_mock()
    c.ingest.events.clear()
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.http.request.await_count == 0  # The report-directory fixture is injected separately.
    assert [e.raw_payload['unit'] for e in c.ingest.events] == ['manifest']
    assert c.stats['reused_securities'] == len(units)
    assert c.stats['assembled_securities'] == 0
    c.query.securities.return_value[0]['name'] = '名称修订'
    c.ingest.events.clear()
    await c.execute(baseline_revision=c.ingest.state['revision'])
    assert c.stats['assembled_securities'] == 1
    assert c.ingest.events[0].raw_payload['rows'][0]['name'] == '名称修订'


def test_expired_and_future_proofs_cannot_skip_or_borrow_manifest_time():
    now = datetime.now(UTC)
    proof = dict(count=0, digest='a' * 64, observed_at=(now - timedelta(days=94)).isoformat())
    assert needs_review(proof, 'old', now)
    assert not proofs_fresh({'old': proof}, now, lambda _: False)
    proof['observed_at'] = (now + timedelta(seconds=1)).isoformat()
    assert needs_review(proof, 'old', now)
    proof['observed_at'] = now.isoformat()
    assert not needs_review(proof, 'old', now)
    assert needs_review(proof, 'old', now, force=True)


def test_recovery_is_bounded_copied_and_expires():
    stage, now = RecoveryStage(), datetime.now(UTC)
    stage.begin(['batch', 'month'], now)
    stage.put('one', [{'value': 1}])
    stage.get('one')[0]['value'] = 2
    assert stage.get('one') == [{'value': 1}]
    stage.put('large', 'x' * (8 * 1024**2))
    assert stage.get('large') is None
    stage.begin(['batch', 'month'], now + timedelta(minutes=31))
    assert stage.get('one') is None
    stage.put('one', [])
    stage.begin(['next-batch', 'month'], now + timedelta(minutes=31))
    assert stage.get('one') is None


async def test_nested_details_keep_accumulated_results_in_budget():
    from empire.plugins.collection.followup_reads import followup_reads
    from empire.plugins.infra.resources import ByteBudget
    budget = ByteBudget(120)
    owner = budget.try_reserve(100)
    held, requests = 20, []

    async def fetch(unit, *, reservation):
        requests.append(reservation.size)
        assert not reservation.grow_to(121)
        return unit

    try:
        collector = SimpleNamespace(http=SimpleNamespace(response_policy=lambda _: SimpleNamespace(reservation_bytes=80)))
        async with followup_reads(collector, [1, 2], fetch, owner, lambda: held) as reads:
            async for _, read in reads:
                await read.resolve()
                held += 20
        assert requests == [80, 80]
    finally:
        owner.release()
    assert budget.used == 0
