"""Forex source semantics, conservative date boundary and SQL-free live task."""
import copy
import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.contracts.data import make_envelope
from empire.core.time import CHINA
from empire.features.fx.collector import FxDailyCollector
from empire.features.fx.contract import DAILY_JOB, DATASET, LIVE_JOB, number
from empire.features.fx.dataset import fingerprint_plan, normalize
from empire.features.fx.live import FxLiveCollector
from empire.features.fx.planning import full_years, tail
from empire.features.fx.source import annual, closed_through, realtime, recent
from tests.prefetch_source import prefetch_http
from tests.test_yuanhang_indices import configured as index_collector

CODE = 'USDCNH'
ROWS = [['2025-12-30', '6', '7', '5', '6.5'], ['2025-12-31', '6.5', '8', '6', '7'],
        ['2026-01-02', '7', '8', '6', '7.5']]
NOW = datetime(2026, 1, 3, 9, tzinfo=CHINA)


def source(unit='last', rows=None, **changes):
    rows = copy.deepcopy(ROWS if rows is None else rows)
    body = dict(data=';'.join(','.join([r[0].replace('-', ''), *r[1:], '0', '0', '', '', '', '0']) for r in rows))
    if unit == 'last':
        body.update(num=len(rows), total='3', start='20251230', year={'2025': 2, '2026': 1})
    body.update(changes)
    return f'quotebridge_v4_line_wh_{CODE}_01_{unit}({json.dumps(body)})'


def live_source(code=CODE, **changes):
    items = {'5': code, 'marketid': '97', '10': '6.75000', '7': '6.74', '8': '6.8',
             '9': '6.7', '6': '6.74', 'time': '2026-01-03 09:00:00 北京时间', 'updateTime': '2026-01-03 05:59'}
    items.update(changes)
    return f'quotebridge_v4_realhead_wh_{code}_last({json.dumps(dict(items=items))})'


def today_source(row=None, code=CODE, **changes):
    row = ROWS[-1] if row is None else row
    item = dict(zip(('1', '7', '8', '9', '11'), [row[0].replace('-', ''), *row[1:]], strict=True), open=1)
    item.update(changes)
    return f'quotebridge_v6_line_wh_{code}_01_today({json.dumps({"wh_" + code: item})})'


def envelope(rows=None, year=2025, mode='full', **changes):
    payload = dict(page=1, code=CODE, year=year, mode=mode, source_count=2,
        start=ROWS[0][0], end=ROWS[-1][0], rows=copy.deepcopy(ROWS[:2] if rows is None else rows))
    payload.update(changes)
    return make_envelope(source='ths', dataset=DATASET, business_key=f'{CODE}:{year}',
        job_key=DAILY_JOB, batch_id='fx-test', run_id='fx-test', payload=payload)


def collector():
    c, helper = FxDailyCollector(), index_collector()
    c.ingest, c.records, c.confirmation = helper.ingest, helper.records, helper.confirmation
    c.selected_codes = [CODE]
    c.query = SimpleNamespace(inventory=AsyncMock(return_value={CODE: {}}))
    def request(method, url, **kw):
        if '/today.js' in url:
            return httpx.Response(200, content=today_source().encode())
        unit = url.rsplit('/', 1)[1].split('.')[0]
        rows = ROWS if unit == 'last' else [r for r in ROWS if r[0][:4] == unit]
        return httpx.Response(200, content=source(unit, rows).encode())
    c.http = prefetch_http(request=AsyncMock(side_effect=request), response_policy=lambda _: None)
    return c


def test_identity_precision_and_annual_recent_cache_reconciliation():
    snapshot = recent(source(), CODE, NOW)
    assert annual(source(2025, ROWS[:2]), CODE, 2025, snapshot) == ROWS[:2]
    assert number('6.0000000000') == '6'
    for value in ('NaN', '0', '-1', '1e2', '1.00000000001', '10000000000'):
        with pytest.raises(ValueError):
            number(value)
    changed = copy.deepcopy(ROWS)
    changed[1][4] = '6.9'
    snapshot = recent(source(rows=changed), CODE, NOW)
    assert annual(source(2025, ROWS[:2]), CODE, 2025, snapshot)[1][4] == '6.9'
    with pytest.raises(ValueError):
        annual(source(2025, [ROWS[0], ['2025-12-29', '6', '7', '5', '6']]), CODE, 2025, snapshot)


@pytest.mark.parametrize('body', [source()[:-1], '<html>login</html>', source(rows=ROWS[::-1]),
    source(rows=[ROWS[0], ROWS[0], ROWS[-1]]), source(total='4'), source(num=2),
    source(year={'2025': 1, '2026': 2}), source().replace('wh_USDCNH', 'wh_EURUSD')])
def test_invalid_source_never_proves_completeness(body):
    with pytest.raises(ValueError):
        recent(body, CODE, NOW)


@pytest.mark.parametrize('stamp,expected', [('2026-01-01T08:59:59+08:00', '2025-12-30'),
    ('2026-01-01T09:00:00+08:00', '2025-12-31'), ('2026-03-08T09:00:00+08:00', '2026-03-07'),
    ('2026-11-01T09:00:00+08:00', '2026-10-31')])
def test_boundary_is_source_labels_without_a_share_or_dst_calendar(stamp, expected):
    assert closed_through(datetime.fromisoformat(stamp)) == expected


def test_current_label_excluded_and_both_source_times_preserved():
    snapshot = recent(source(), CODE, datetime(2026, 1, 2, 9, tzinfo=CHINA))
    assert snapshot['end'] == '2025-12-31' and '2026' not in snapshot['years']
    value = realtime(live_source(), CODE, NOW)
    assert value['latest'] == '6.75' and value['source_time'] != value['source_update_time']
    with pytest.raises(ValueError):
        realtime(live_source(), CODE, datetime(2025, 1, 1, tzinfo=UTC))


def test_same_count_changed_membership_and_incremental_gap_planning():
    snap = recent(source(), CODE, NOW)
    heads = {'2025': dict(contract_version=1, row_count=2, last_date='2025-12-31', dates=[r[0] for r in ROWS[:2]]),
             '2026': dict(contract_version=1, row_count=1, last_date='2026-01-02', dates=[ROWS[-1][0]])}
    assert full_years(snap, heads) == []
    heads['2025']['dates'] = ['2025-12-29', '2025-12-31']
    assert full_years(snap, heads) == [2025]
    assert full_years(snap, {}, fresh=False) == [2025, 2026]
    assert full_years(snap, heads, fresh=True) == [2025, 2026]
    heads['2025'].update(last_date='2025-01-01')
    assert 2025 in full_years(snap, heads)
    assert tail(snap) == ROWS


def test_live_envelopes_rejected_and_fingerprint_has_no_run_identity():
    e = envelope()
    assert fingerprint_plan(e, normalize(e)) == fingerprint_plan(e.model_copy(update={'batch_id': 'other'}), normalize(e))
    with pytest.raises(ValueError, match='实时任务'):
        normalize(e.model_copy(update={'job_key': LIVE_JOB}))


async def test_daily_enqueues_all_years_before_archive_wait_and_recovery():
    c = collector()
    async def confirm(*args):
        assert len(c.ingest.events) == 2
        return {'status': 'complete'}
    c.confirmation.page_status.side_effect = confirm
    result = await c.execute()
    assert result['collected'] == 3 and c.http.request.await_count == 4
    assert c.ingest.events[0].raw_payload['year'] == 2025


async def test_live_does_not_use_checkpoints_or_archival_or_sql():
    c, helper = FxLiveCollector(), collector()
    c.selected_codes = [CODE]
    c.http = prefetch_http(request=AsyncMock(return_value=httpx.Response(200, content=live_source().encode())), response_policy=lambda _: None)
    c.records = helper.records
    c.store = SimpleNamespace(save=AsyncMock())
    class Admission:
        stats = {}
        ensure_capacity = AsyncMock()
        async def capacity_status(self):
            return {'blocked': False}
        async def publish_volatile(self, project, commit):
            assert project == 'ths-fx-live'
            return await commit()
    c.ingest = Admission()
    assert await c.checkpoint_revision() == 0
    result = await c.execute()
    assert result['storage'] == 'redis_only' and c.store.save.await_count == 1


async def test_interruption_resumes_after_last_enqueued_year_without_waiting_for_it():
    c = collector()
    original = c.http.request.side_effect
    def interrupted(method, url, **kw):
        if '/2026.js' in url:
            raise ValueError('one failed year')
        return original(method, url, **kw)
    c.http.request.side_effect = interrupted
    with pytest.raises(ValueError, match='failed year'):
        await c.execute()
    assert len(c.ingest.events) == 1 and c.ingest.state['cursor']['next_year'] == 2026
    c.confirmation.page_status.assert_not_awaited()
    c.http.request.side_effect = original
    await c.execute()
    assert [e.raw_payload['year'] for e in c.ingest.events] == [2025, 2026]


def test_delayed_source_never_plans_rollback_of_a_confirmed_later_day():
    snapshot = recent(source(), CODE, NOW)
    heads = {'2025': dict(contract_version=1, row_count=2, last_date='2025-12-31', dates=[r[0] for r in ROWS[:2]]),
             '2026': dict(contract_version=1, row_count=2, last_date='2026-01-03', dates=['2026-01-02', '2026-01-03'])}
    assert full_years(snapshot, heads) == []
    assert full_years(snapshot, heads, fresh=True) == [2025]
