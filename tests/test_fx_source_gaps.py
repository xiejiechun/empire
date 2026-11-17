"""An unresolved symbol cannot block siblings or advance its resume position."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest

from empire.contracts.collector import CollectionSourceGap
from tests.test_fx import CODE, collector, source, today_source
from tests.test_fx_verification import CLOSED, CURRENT, NOW, OLD

CODES = ['USDIND', 'XAUUSD', 'EURUSD']


def gap_collector(monkeypatch, bad_code):
    monkeypatch.setattr('empire.features.fx.transport.datetime', SimpleNamespace(now=lambda _: NOW))
    c = collector()
    c.selected_codes = CODES
    c.query.inventory.return_value = {code: {} for code in CODES}
    faults = {bad_code}
    def request(method, url, **kwargs):
        code = url.split('wh_')[1].split('/')[0]
        if '/today.js' in url:
            body = today_source(CURRENT, code=code)
        else:
            unit = url.rsplit('/', 1)[1].split('.')[0]
            rows = ([CLOSED] if unit == 'last' else [OLD]) if code in faults else [CLOSED, CURRENT]
            changes = dict(start=CLOSED[0].replace('-', ''), year={'2026': 2}, total='2') if unit == 'last' else {}
            body = source(unit, rows, **changes).replace('wh_' + CODE, 'wh_' + code)
        return httpx.Response(200, content=body.encode())
    c.http.request.side_effect = request
    return c, faults


@pytest.mark.parametrize('failed_index', range(3))
async def test_source_gap_archives_all_siblings_and_resumes_first_unresolved(monkeypatch, failed_index):
    bad_code = CODES[failed_index]
    c, faults = gap_collector(monkeypatch, bad_code)
    async def confirm(*args):
        assert {e.raw_payload['code'] for e in c.ingest.events} == set(CODES) - faults
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    with pytest.raises(CollectionSourceGap, match=bad_code):
        await c.execute()
    cursor = c.ingest.state['cursor']
    assert cursor['next_index'] == failed_index and cursor['phase'] == 'collecting'
    assert cursor['pages'] == 2 and cursor['collected'] == 2
    assert c.stats['status'] == 'source_gap' and c.stats['completed_units'] == 2
    assert c.stats['unavailable_codes'] == [bad_code]
    c.confirmation.page_status.assert_awaited_once()
    faults.clear()
    c.confirmation.page_status.side_effect = None
    c.confirmation.page_status.return_value = {'status': 'complete'}
    c.http.request.reset_mock()
    assert (await c.execute())['phase'] == 'complete'
    requested = [call.args[1].split('wh_')[1].split('/')[0] for call in c.http.request.await_args_list]
    assert set(requested) == set(CODES[failed_index:])
    assert c.stats['completed_units'] == 3 and c.stats['unavailable_codes'] == []
    assert any(e.raw_payload['code'] == bad_code for e in c.ingest.events)


async def test_gap_archive_failure_is_not_reported_as_confirmed_source_gap(monkeypatch):
    c, _ = gap_collector(monkeypatch, 'XAUUSD')
    c.confirmation.page_status.side_effect = RuntimeError('archive unavailable')
    with pytest.raises(RuntimeError, match='archive unavailable'):
        await c.execute()
    assert c.stats['status'] == 'paused' and c.ingest.state['cursor']['next_index'] == 1


async def test_recent_only_gap_reports_actual_enqueued_rows(monkeypatch):
    c, _ = gap_collector(monkeypatch, 'XAUUSD')
    c.query.inventory.return_value = {code: {'2026': dict(contract_version=1,
        row_count=1, last_date=CLOSED[0], dates=[CLOSED[0]])} for code in CODES}
    with pytest.raises(CollectionSourceGap):
        await c.execute()
    assert c.ingest.state['cursor']['collected'] == 2
    assert c.stats['collected'] == 2 and c.stats['pages'] == 2
    assert all(e.raw_payload['mode'] == 'recent' for e in c.ingest.events)


async def test_first_gap_retains_existing_year_resume_while_siblings_initialize(monkeypatch):
    c, faults = gap_collector(monkeypatch, 'USDIND')
    faults.add('XAUUSD')
    c.ingest.state['cursor'] = dict(phase='collecting', codes=CODES, next_index=0,
        next_year=2027, snapshot_hash='existing-resume', pages=0, collected=0, batch_id='resume', fresh=False)
    with pytest.raises(CollectionSourceGap, match='USDIND、XAUUSD'):
        await c.execute()
    cursor = c.ingest.state['cursor']
    assert (cursor['next_index'], cursor['next_year'], cursor['snapshot_hash']) == (0, 2027, 'existing-resume')
    assert [e.raw_payload['code'] for e in c.ingest.events] == ['EURUSD']
    assert c.stats['completed_units'] == 1


@pytest.mark.parametrize('failure', [httpx.ProxyError('unavailable'), asyncio.CancelledError()])
async def test_network_failure_and_cancellation_are_not_swallowed(monkeypatch, failure):
    c, _ = gap_collector(monkeypatch, 'XAUUSD')
    c.http.request.side_effect = failure
    with pytest.raises(type(failure)):
        await c.execute()
    assert not c.ingest.events and c.stats['status'] == 'paused'
