"""Independent cash arithmetic, event boundaries and fail-closed readiness."""
from copy import deepcopy
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.contracts.preparation import CheckEvidence
from empire.features.capital_actions.distribution import nominal_rows, summarize_distribution
from empire.features.capital_actions.event_rules import ActionError, actions
from empire.features.preparation.products import attach_products
from tests.test_adjustment import dividend


def records():
    rows = [dividend('2026-06-12', '0.36', key='annual'),
            dividend('2026-09-24', '0.249', key='interim')]
    for row, report in zip(rows, ('2025-12-31', '2026-06-30'), strict=True):
        row['data']['report_date'] = report
    return rows


@pytest.mark.parametrize(('end', 'expected', 'ten'), [
    ('2026-06-11', '0', '0'), ('2026-06-12', '0.36', '3.6'),
    ('2026-09-23', '0.36', '3.6'), ('2026-09-24', '0.609', '6.09')])
def test_manual_decimal_oracle_and_closed_endpoints(end, expected, ten):
    original = records()
    rows = deepcopy(original)
    result = nominal_rows(rows, '2026-01-01', end)
    assert (result['cash_per_share'], result['cash_per_ten']) == (expected, ten)
    assert rows == original  # Analysis never rewrites history.
    assert [r['record_key'] for r in result['rows']] == [
        r['record_key'] for r in rows if r['data']['ex_date'] <= end]


def test_summary_includes_first_day_but_adjustment_normalizes_it_away():
    rows = records()
    assert nominal_rows(rows, '2026-06-12', '2026-06-12')['cash_per_share'] == '0.36'
    assert actions(rows, [], '2026-06-12', '2026-06-12') == {}
    assert nominal_rows(rows, '2026-06-13', '2026-09-24')['cash_per_share'] == '0.249'


def test_no_per_event_rounding_and_shares_not_required_for_nominal_cash():
    rows = records()
    for row in rows:
        row['data'].update(cash_per_share='0.000000000000000000000000001', total_bonus_per_share=None)
    result = nominal_rows(rows, '2026-01-01', '2026-10-20')
    assert result['cash_per_share'] == '0.000000000000000000000000002'
    assert result['cash_per_ten'] == '0.00000000000000000000000002'
    with pytest.raises(ActionError, match='未知'):
        actions(rows, [], '2026-01-01', '2026-10-20')


@pytest.mark.parametrize('status', ['董事会预案', '股东大会预案', '公司预案', '取消分红', '终止'])
def test_preserved_proposals_never_count(status):
    rows = records() + [dividend(None, None, key='proposal', status=status)]
    before = deepcopy(rows)
    assert nominal_rows(rows, '2026-01-01', '2026-10-20')['cash_per_share'] == '0.609'
    assert rows == before


@pytest.mark.parametrize('case', ['parallel', 'cross_range_report', 'missing_date', 'missing_cash',
                                 'duplicate', 'unknown_status', 'tax'])
def test_ambiguity_and_required_unknowns_block_instead_of_guessing(case):
    rows = records()
    if case == 'parallel':
        rows.append(dividend('2026-06-12', '0.1', key='parallel'))
    elif case == 'cross_range_report':
        row = dividend('2025-12-31', '0.3', key='outside')
        row['data']['report_date'] = '2025-12-31'
        rows.append(row)
    elif case == 'duplicate':
        rows.append(deepcopy(rows[0]))
    else:
        field, value = {'missing_date': ('ex_date', None), 'missing_cash': ('cash_per_share', None),
            'unknown_status': ('status', '未知'), 'tax': ('tax_basis', '税后')}[case]
        rows[0]['data'][field] = value
    with pytest.raises(ActionError):
        nominal_rows(rows, '2026-01-01', '2026-10-20')


@pytest.mark.parametrize('case', ['passed', 'empty_proven', 'missing_proof', 'historical_signal', 'missing_identity'])
async def test_result_states_never_confuse_unproved_empty_with_zero(monkeypatch, case):
    stamp = datetime.now(UTC).isoformat()
    checks = [CheckEvidence('coverage', 'fail' if case == 'missing_proof' else 'pass', 'exact unit', observed_at=stamp)]
    if case == 'historical_signal':
        checks.append(CheckEvidence('temporal', 'fail', '修订可用日缺失', reason='source_limit'))
    units = {} if case == 'missing_identity' else {'000001.SZ': [] if case == 'empty_proven' else records()}
    monkeypatch.setattr('empire.features.capital_actions.distribution.checked_units', AsyncMock(return_value=(checks, units)))
    result = await summarize_distribution(None, dict(codes=['000001'], start='2026-01-01', end='2026-10-20',
        purpose='historical_signal' if case == 'historical_signal' else 'analysis'))
    expected = {'passed': '已计算', 'empty_proven': '已计算', 'historical_signal': '来源受限'}.get(case, '数据阻断')
    assert result['state'] == expected
    if expected == '已计算':
        assert result['securities'][0]['cash_per_share'] == ('0' if case == 'empty_proven' else '0.609')
    else:
        assert result['securities'] == []
    assert result['observed_at'] == stamp


async def test_repurchase_theme_blocker_does_not_propagate_to_independent_dividend_product():
    report = dict(rows=[dict(id='dividends', required=True), dict(id='repurchases', complete=False)],
                  research=dict(ready=False))
    service = SimpleNamespace(distribution_summary=AsyncMock(return_value=dict(
        id='nominal_dividends', title='已实施名义每股派息', state='已计算')))
    await attach_products(report, SimpleNamespace(optional=lambda k: service if k == 'dividends.query' else None),
        dict(codes=['000001'], start='2026-01-01', end='2026-10-20'))
    assert report['products'][0]['state'] == '已计算' and not report['research']['ready']
    assert all(p['state'] == '功能未实现' for p in report['products'][1:])
    assert report['rows'][0]['products'] is report['products']
