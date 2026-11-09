"""Current-quarter previews traverse the formal archive without skipping history."""
import asyncio
import json
import os
from unittest.mock import AsyncMock

import httpx
import pytest

from tests.capital_samples import source
from tests.integration import test_capital_archive as archive_tests
from tests.test_tdx_dividends import freeze_plan_day

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.environ.get('EMPIRE_INTEGRATION') != '1', reason='Set EMPIRE_INTEGRATION=1 explicitly')]
capital_db = archive_tests.capital_db


@pytest.mark.parametrize('capital_db', ['dividends'], indirect=True)
@pytest.mark.parametrize('selected', ['2026-09-30', '2026-12-31'])
async def test_preview_and_historical_scheme_archive_then_reuse(capital_db, monkeypatch, selected):
    manager, query, collector, _ = capital_db
    freeze_plan_day(monkeypatch)
    query.dividend_report_dates = AsyncMock(return_value=['2000-05-31'])
    calls = []
    async def request(method, url, **kw):
        params = json.loads(kw['content'])['Params']
        calls.append(params)
        if params[0] == 'fhszdate':
            body = dict(ErrorCode=0, ResultSets=[dict(ColName=['T002', 'maxrq'], Count=2,
                Content=[['2026-12-31', selected], ['2026-09-30', selected]])])
        else:
            period = params[2]
            body = source('dividends', rows=None if period in ('2000-05-31', '2026-12-31') else [])
            body['ResultSets'][1]['Content'][0][-1] = period
            if period == '2026-12-31':
                columns = body['ResultSets'][0]['ColName']
                row = body['ResultSets'][0]['Content'][0]
                row[columns.index('fajd')] = '公司预案'
                row[columns.index('cqcxr')] = None
                row[columns.index('gqdjr')] = None
        return httpx.Response(200, json=body)
    collector.http.request.side_effect = request
    result = await asyncio.wait_for(collector.execute(), 30)
    assert result['collected'] == 2
    rows = await query.list_events()
    assert {r['data']['report_date'] for r in rows} == {'2000-05-31', '2026-12-31'}
    preview = next(r for r in rows if r['data']['report_date'] == '2026-12-31')
    assert preview['data']['status'] == '公司预案' and preview['data']['ex_date'] is None
    assert {p[2] for p in calls[1:]} >= {'2000-05-31', '2026-10-15', '2026-11-09', '2026-12-31'}
    assert len(calls) == len({tuple(p) for p in calls})
    store = manager.registry.get('redis.store')
    assert await store.client.xlen(store.stream) == 0
    before = len(calls)
    await collector.execute(baseline_revision=await collector.checkpoint_revision())
    assert calls[before:] == [['fhszdate', '', '', '']]
    assert collector.stats['downloaded_report_periods'] == 0
    assert await query.list_events() == rows and await store.client.xlen(store.stream) == 0
