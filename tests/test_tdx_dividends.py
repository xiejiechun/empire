import copy
from unittest.mock import AsyncMock

import httpx
import pytest

from empire.plugins.collectors.tdx_capital_source import parse
from empire.plugins.collectors.tdx_dividend_periods import period_plan
from empire.plugins.collectors.tdx_dividends import TdxDividendsCollector
from empire.plugins.datasets.capital_actions import DIVIDEND_COLUMNS, source_row, validate_rows
from empire.plugins.datasets.capital_validation import as_source
from tests.capital_samples import STOCK, source
from tests.test_capital_lifecycle import configured

PERIOD = '2025-12-31'


@pytest.mark.parametrize('selected', ['2026-06-30', '2026-09-30'])
async def test_selector_default_may_lag_newest_quarter_without_losing_open_dates(selected):
    from empire.plugins.collectors.tdx_dividend_periods import report_periods
    c, _ = configured(TdxDividendsCollector)
    c.query.dividend_report_dates = AsyncMock(return_value=['2000-05-31'])
    body = dict(ErrorCode=0, ResultSets=[dict(ColName=['T002', 'maxrq'], Count=2,
        Content=[['2026-09-30', selected], ['2026-06-30', selected]])])
    c.http.request = AsyncMock(return_value=httpx.Response(200, json=body))
    periods = await report_periods(c)
    assert {'2026-09-30', '2026-06-30', '2000-05-31'} <= set(periods)
    if selected == '2026-06-30':
        assert '2026-07-15' in periods
    body['ResultSets'][0]['Content'][1][1] = '2025-12-31'
    c.http.request.return_value = httpx.Response(200, json=body)
    with pytest.raises(ValueError, match='目录'):
        await report_periods(c)


def test_period_contains_multiple_securities_and_preserves_parallel_payouts():
    body = source('dividends', amount=8)
    parallel = copy.deepcopy(body['ResultSets'][0]['Content'][0])
    parallel[7] = 5
    other = copy.deepcopy(parallel)
    other[1] = '688111'
    body['ResultSets'][0].update(Content=[parallel, other, body['ResultSets'][0]['Content'][0]], Count=3)
    body['ResultSets'][2]['Content'] = [[3]]
    rows, total = parse('dividends', body, 10000, PERIOD)
    assert total == 3 and len({r['record_key'] for r in rows}) == 3
    group = [r for r in rows if r['code'] == '688110']
    assert {r['data']['cash_per_share'] for r in group} == {'0.5', '0.8'}
    validate_rows('dividends', 'SH:688110', group)
    body['ResultSets'][0]['Content'].reverse()
    assert parse('dividends', body, 10000, PERIOD)[0] == rows


def test_null_and_zero_amount_identity_matches_without_rewriting_source_values():
    row = parse('dividends', source('dividends'), 10000, PERIOD)[0][0]
    raw, stock = as_source('dividends', row)
    raw['T013'] = None
    old = source_row('dividends', raw, stock)
    assert old['record_key'] == row['record_key']
    assert old['data']['bonus_per_share'] is None and row['data']['bonus_per_share'] == '0'


@pytest.mark.parametrize('problem', ['metadata', 'total', 'count', 'duplicate', 'capacity', 'columns'])
def test_invalid_period_cannot_be_accepted(problem):
    body = source('dividends')
    capacity = 10000
    if problem == 'metadata':
        body['ResultSets'][1]['Content'][0][-1] = '2024-12-31'
    if problem == 'total':
        body['ResultSets'][2]['Content'] = [[2]]
    if problem == 'count':
        body['ResultSets'][0]['Count'] = 2
    if problem == 'duplicate':
        body['ResultSets'][0].update(Content=body['ResultSets'][0]['Content'] * 2, Count=2)
        body['ResultSets'][2]['Content'] = [[2]]
    if problem == 'capacity':
        capacity = 1
    if problem == 'columns':
        body['ResultSets'][0]['ColName'][0] = 'unknown'
    with pytest.raises(ValueError):
        parse('dividends', body, capacity, PERIOD)


def test_exact_count_zero_response_and_valid_empty_period():
    body = source('dividends')
    body['ResultSets'].pop()
    assert len(parse('dividends', body, 10000, PERIOD)[0]) == 1
    assert parse('dividends', source('dividends', rows=[]), 10000, PERIOD)[0] == []


def test_quarter_plan_retains_old_history_and_known_nonquarter_dates():
    dates = period_plan('2026-06-30', ['1995-12-31', '2000-05-31'])
    assert dates[0] == '1980-03-31' and '2026-06-30' in dates
    assert '1990-12-31' in dates and '2000-05-31' in dates
    assert len(dates) < 500 and dates == sorted(set(dates))
    assert '2026-09-12' in period_plan('2026-06-30', ['2026-09-12'])
    with pytest.raises(ValueError):
        period_plan('2026-06-30', ['1979-12-31'])


@pytest.mark.parametrize('fail', [False, True])
async def test_full_history_reports_once_and_failure_never_publishes_partial_security(monkeypatch, fail):
    c, calls = configured(TdxDividendsCollector)
    monkeypatch.setattr('empire.plugins.collectors.tdx_dividend_periods.report_periods',
                        AsyncMock(return_value=['1995-12-31', PERIOD]))
    async def request(method, url, **kwargs):
        import json
        params = json.loads(kwargs['content'])['Params']
        calls.append(params)
        if fail and params[2] == PERIOD:
            return httpx.Response(200, json={'ErrorCode': -1005})
        body = source('dividends')
        body['ResultSets'][1]['Content'][0][-1] = params[2]
        return httpx.Response(200, json=body)
    c.http.request.side_effect = request
    if fail:
        with pytest.raises(ValueError):
            await c.execute()
        assert c.ingest.events == [] and c.ingest.state['revision'] == 0
    else:
        assert (await c.execute())['collected'] == 2
        dates = {r['data']['report_date'] for e in c.ingest.events for r in e.raw_payload['rows']}
        assert dates == {'1995-12-31', PERIOD}
    assert calls == [['0', '0', d, 'szzs desc', '', '0', '1', '10000'] for d in ('1995-12-31', PERIOD)]
    assert c.http.buffer_budget.used == 0


def directory(period='2000-05-31'):
    row = parse('dividends', source('dividends'), 10000, PERIOD)[0][0]
    raw, _ = as_source('dividends', row)
    raw['fhbgq'] = period
    return dict(ErrorCode=0, ResultSets=[
        dict(Count=1, ColName=list(DIVIDEND_COLUMNS), Content=[[raw[k] for k in DIVIDEND_COLUMNS]]),
        dict(Count=1, ColName=['page', 'nzt', 'nflag', 'strjzr'], Content=[[1, 1, 1, '1']]),
        dict(Count=1, ColName=['count'], Content=[[1]])])


@pytest.mark.parametrize('missing', [False, True])
async def test_history_discovery_adds_nonquarter_and_requires_business_keys(monkeypatch, missing):
    from empire.plugins.collectors.tdx_dividend_periods import collect_history
    c, calls = configured(TdxDividendsCollector)
    c.query.securities.return_value = [STOCK]
    c.query.dividend_history_proofs.return_value = {}
    periods = AsyncMock(return_value=['2000-05-31'])
    monkeypatch.setattr('empire.plugins.collectors.tdx_dividend_periods.report_periods', periods)
    async def request(method, url, **kw):
        import json
        params = json.loads(kw['content'])['Params']
        calls.append(params)
        body = directory() if params[0] == '1' else source('dividends', rows=[] if missing else None)
        if params[0] == '0':
            body['ResultSets'][1]['Content'][0][-1] = params[2]
        return httpx.Response(200, json=body)
    c.http.request.side_effect = request
    if missing:
        with pytest.raises(ValueError, match='未覆盖历史目录'):
            await collect_history(c)
    else:
        units, _, _ = await collect_history(c)
        assert len(units['SH:688110']) == 1
        assert c.history_discoveries['SH:688110']
    assert periods.call_args.args[1] == {'2000-05-31'}
    assert calls[0] == ['1', '1', '1', '', '688110', '1', '1', '1']
    assert c.ingest.events == [] and c.http.buffer_budget.used == 0


async def test_explicit_refresh_reenumerates_proven_security(monkeypatch):
    from empire.plugins.collectors.tdx_dividend_periods import collect_history
    c, _ = configured(TdxDividendsCollector)
    c.query.securities.return_value = [STOCK]
    discover = AsyncMock(return_value=(set(), {}))
    monkeypatch.setattr('empire.plugins.collectors.tdx_dividend_discovery.discover', discover)
    monkeypatch.setattr('empire.plugins.collectors.tdx_dividend_periods.report_periods', AsyncMock(return_value=[PERIOD]))
    await collect_history(c, force_history=True)
    assert discover.call_args.args[1] == {'SH:688110': STOCK}


@pytest.mark.parametrize('problem', ['total', 'metadata', 'duplicate', 'capacity'])
def test_history_directory_rejects_invalid_evidence(problem):
    from empire.plugins.collectors.tdx_dividend_discovery import parse_directory
    body = directory()
    if problem == 'total':
        body['ResultSets'][2]['Content'] = [[2]]
    if problem == 'metadata':
        body['ResultSets'][1]['Content'][0][0] = 2
    if problem in ('duplicate', 'capacity'):
        size = 2 if problem == 'duplicate' else 2001
        body['ResultSets'][0]['Content'] *= size
        body['ResultSets'][0]['Count'] = size
    with pytest.raises(ValueError):
        parse_directory(body, STOCK)


@pytest.mark.parametrize('stamp', ['2026-01-01T00:00:00', '2099-01-01T00:00:00+00:00'])
def test_archive_rejects_naive_or_future_history_proof(stamp):
    from empire.contracts.data import make_envelope
    from empire.plugins.datasets.capital_archive import CapitalDataset
    envelope = make_envelope(source='tdx', dataset='dividends.unit', schema_version=3,
        business_key='SH:688110', job_key='tdx-dividends-v1', run_id='test', batch_id='test',
        payload=dict(page=1, unit='SH:688110', rows=[], manifest=None, history_discovered_at=stamp))
    with pytest.raises(ValueError, match='历史日期发现证明'):
        CapitalDataset('dividends').normalize(envelope)
