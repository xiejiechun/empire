"""Only a quote-proven unclosed suffix may extend a stale directory count."""
import copy
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.contracts.collector import CollectionSourceGap
from empire.core.time import CHINA
from empire.features.fx.contract import SYMBOLS
from empire.features.fx.verification import reconcile, verified_snapshot
from tests.test_fx import collector
from tests.test_fx_verification import CLOSED, CURRENT, NOW, snapshot


@pytest.mark.parametrize('code', SYMBOLS)
async def test_stale_directory_accepts_only_new_unclosed_quote_day_for_all_symbols(code):
    initial = snapshot([CLOSED])
    c = SimpleNamespace(stats={}, fetch=AsyncMock(side_effect=[(initial, NOW), CURRENT, [CLOSED, CURRENT]]))
    result, _, verified = await verified_snapshot(c, code)
    assert result['rows'] == [CLOSED] and result['years'] == {'2026': 1}
    assert verified == {2026: [CLOSED]} and c.fetch.await_count == 3


def test_exact_225_vs_224_boundary_keeps_only_224_closed_dates():
    rows = []
    for i in range(314):
        day = date(2026, 1, 1) + timedelta(days=i)
        if day.weekday() < 5:
            rows.append([day.isoformat(), '1', '2', '0.5', '1.5'])
    assert len(rows) == 224 and rows[-1][0] == '2026-11-10'
    today = ['2026-11-11', '1.6', '2', '1.5', '1.7']
    initial = dict(start=rows[0][0], end=rows[-1][0], rows=rows[-140:], source_tail=rows[-2:],
                   years={'2026': 224}, source_years={'2026': 224})
    result, verified = reconcile(initial, {2026: rows + [today]},
                                 datetime(2026, 11, 11, 9, tzinfo=CHINA), today)
    assert result['years']['2026'] == 224 and verified[2026] == rows
    assert result['end'] == '2026-11-10'


@pytest.mark.parametrize('candidate,quote', [
    ([CLOSED, CURRENT], ['2026-11-09', *CURRENT[1:]]),
    ([CLOSED, CURRENT], [CURRENT[0], '6.6', *CURRENT[2:]]),
    ([['2026-11-06', *CLOSED[1:]], CURRENT], CURRENT),
    ([CLOSED, CLOSED, CURRENT], CURRENT),
    ([CLOSED, ['2026-11-11', *CURRENT[1:]]], CURRENT),
    ([['2026-11-06', *CLOSED[1:]], CLOSED, CURRENT], CURRENT),
])
async def test_extra_closed_missing_duplicate_future_or_unproven_dates_fail(candidate, quote):
    initial = snapshot([CLOSED])
    c = collector()
    before = copy.deepcopy(c.ingest.state)
    c.fetch = AsyncMock(side_effect=[(initial, NOW), quote, candidate])
    with pytest.raises(CollectionSourceGap):
        await c.execute()
    assert c.ingest.events == [] and c.ingest.state == before
    c.records.add_error.assert_awaited_once()
    diagnostic = c.records.add_error.call_args.kwargs
    assert diagnostic['metadata']['symbol'] == 'USDCNH'
    assert diagnostic['metadata']['annuals']['2026']['directory'] == 1
    assert diagnostic['metadata']['annuals']['2026']['count'] == len(candidate)
    assert diagnostic['metadata']['kind'] == 'cross_response_validation'
    assert 'raw_body' not in diagnostic


def test_new_year_unclosed_suffix_uses_quote_date_without_writing_new_year():
    end = ['2026-12-31', '1', '2', '0.5', '1.5']
    today = ['2027-01-01', '1.6', '2', '1.5', '1.7']
    initial = dict(start=end[0], end=end[0], rows=[end], source_tail=[end],
                   years={'2026': 1}, source_years={'2026': 1})
    resolved, verified = reconcile(initial, {2026: [end], 2027: [today]},
                                   datetime(2027, 1, 1, 9, tzinfo=CHINA), today)
    assert resolved['years'] == {'2026': 1} and verified == {2026: [end]}
