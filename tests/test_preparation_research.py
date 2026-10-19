"""Research-specific counterexamples and read-only inventory boundaries."""
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import create_engine, text

from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_catalog import BY_ID
from empire.contracts.preparation_research import required_ids, research_guards, research_summary
from empire.contracts.preparation_scope import PreparationScope
from empire.features.financial_statements.query import FinancialDataPlugin
from empire.plugins.data.preparation import PreparationPlugin
from empire.plugins.data.preparation_inventory import count_table, inventory
from empire.plugins.data.preparation_results import summarize
from tests.test_preparation import contribution


def scope(study='factor', focus='price', **kwargs):
    return PreparationScope.parse(dict(study=study, focus=focus, scan='research', **kwargs))


def test_templates_only_require_selected_inputs_and_preserve_dependencies():
    price = required_ids(scope())
    assert {'historical_quote', 'adjusted_prices', 'adjustment_factors'} <= price
    assert not {'income', 'cashflow', 'bond_holders', 'financing', 'index_members'} & price
    value = required_ids(scope('value', 'operating'))
    assert {'income', 'balance', 'cashflow'} <= value
    assert not {'historical_quote', 'limit_rules', 'index_prices'} & value
    backtest = required_ids(scope('backtest', 'quality'))
    assert {'income', 'financial_reconciliation', 'calendar', 'limit_rules', 'index_prices'} <= backtest
    assert 'bond_holders' not in backtest


def test_current_pool_and_raw_input_success_do_not_fake_research_products():
    request = scope()
    rows = [dict(id=key, registered=True, assessment=dict(usable=True, use_state='可用'))
            for key in required_ids(request)]
    result = research_summary(rows, request)
    assert result['counts']['ready'] == len(rows) and not result['ready']
    assert any(g['title'] == '历史股票池' and g['state'] == '阻断' for g in result['guards'])
    fixed = research_guards(scope(codes=['601139'], start='2020-01-01', end='2026-01-01'))
    assert next(g for g in fixed if g['title'] == '历史股票池')['state'] == '有限制'
    assert any(g['state'] == '待建设' for g in fixed)


@pytest.mark.parametrize('value', [dict(study='bad'), dict(study='value', focus='price'),
    dict(study='factor', focus='price', purpose='analysis'), dict(study='factor', focus='price', scan='unsafe')])
def test_scope_rejects_incompatible_time_semantics(value):
    with pytest.raises(ValueError):
        PreparationScope.parse(value)


async def test_selected_research_does_not_scan_unrelated_sources(monkeypatch):
    monkeypatch.setattr('empire.plugins.data.preparation.load_evidence', lambda: ({}, '未发布'))
    stocks = SimpleNamespace(preparation_check=AsyncMock(return_value=tuple(
        CheckEvidence(c.id, 'pass', '来源集合和字段已核验') for c in BY_ID['universe'].criteria)))
    financial = SimpleNamespace(preparation_check=AsyncMock())
    plugin = PreparationPlugin([contribution(), FinancialDataPlugin('income').preparation[0]])
    await plugin.start(SimpleNamespace(optional={'stocks.query': stocks, 'income.query': financial}.get))
    report = await plugin.report(dict(study='factor', focus='price', scan='research'))
    stocks.preparation_check.assert_awaited_once()
    financial.preparation_check.assert_not_awaited()
    row = next(r for r in report['rows'] if r['id'] == 'universe')
    assert row['complete'] and row['assessment']['development'] != '通过'
    assert row['collection_state'] == '已完成（声明范围）'
    assert report['total_requirements'] == len(required_ids(scope()))


async def test_financial_announcement_limit_is_blocking_only_for_historical_study(monkeypatch):
    monkeypatch.setattr('empire.plugins.data.preparation.load_evidence', lambda: ({}, '未发布'))
    c = FinancialDataPlugin('income').preparation[0]
    async def check(request):
        historical = PreparationScope.parse(request).purpose == 'historical_signal'
        return tuple(CheckEvidence(k.id, 'fail' if k.id == 'temporal' else 'pass', '无实际公告日期',
                                   blocking=historical or k.id != 'temporal') for k in BY_ID['income'].criteria)
    plugin = PreparationPlugin([c])
    await plugin.start(SimpleNamespace(optional={c.capability: SimpleNamespace(preparation_check=check)}.get))
    for study, focus, usable in [('value', 'operating', True), ('factor', 'quality', False)]:
        report = await plugin.report(dict(study=study, focus=focus, scan='research'))
        row = next(r for r in report['rows'] if r['id'] == 'income')
        assert row['assessment']['usable'] is usable
        assert row['collection_state'] == '已完成（声明范围）'


async def test_overview_does_not_start_any_deep_check(monkeypatch):
    monkeypatch.setattr('empire.plugins.data.preparation.load_evidence', lambda: ({}, '未发布'))
    service = SimpleNamespace(preparation_check=AsyncMock())
    plugin = PreparationPlugin([contribution()])
    await plugin.start(SimpleNamespace(optional={'stocks.query': service}.get))
    report = await plugin.overview(dict(study='value', focus='operating', scan='research'))
    service.preparation_check.assert_not_awaited()
    assert report['checked_requirements'] == 0 and report['checked_at'] == ''
    assert report['inventory']['error'] and not any(r['complete'] for r in report['rows'])


def test_partial_coverage_cannot_claim_whole_range_quality():
    checks = [dict(id=k, phase='数据', status='fail' if k == 'coverage' else 'pass')
              for k in ('keys', 'coverage', 'fields', 'quality', 'temporal', 'freshness')]
    result = summarize(checks)
    assert result['quality'] == '已查部分通过' and not result['usable']


def test_exact_inventory_reads_counts_and_edges_without_business_payload():
    engine = create_engine('sqlite://')
    with engine.begin() as conn:
        conn.execute(text('CREATE TABLE example (unified_code TEXT, report_date TEXT, payload TEXT)'))
        conn.execute(text("INSERT INTO example VALUES ('600000.SH','2020-03-31','private'),"
                          "('600000.SH','2020-12-31','private'),('000001.SZ','2020-06-30','private')"))
    row = dict(table='example', date_column='report_date', security_column='unified_code')
    result = count_table(engine, row)
    assert result['count'] == 3 and result['securities'] == 2
    assert result['first'] == '2020-03-31' and result['last'] == '2020-12-31'
    assert 'private' not in str(result) and '完整性另查' in result['status']
    invalid = count_table(engine, {**row, 'table': 'example; DROP TABLE example'})
    assert '安全盘点范围' in invalid['status']
    engine.dispose()


async def test_inventory_failure_never_returns_zero_rows(monkeypatch):
    from empire.plugins.data import preparation_inventory
    row = dict(table='example', count=None, status='未查')
    monkeypatch.setattr(preparation_inventory, 'metadata', lambda *args: [row])
    async def read(operation, *args):
        if operation == preparation_inventory.count_table:
            raise TimeoutError('password=secret')
        return operation(*args)
    mysql = SimpleNamespace(read=read, read_engine=object())
    report = await inventory(SimpleNamespace(optional=lambda _: mysql), (), True)
    assert report['rows'][0]['count'] is None
    assert '未确认' in report['rows'][0]['status'] and 'secret' not in str(report)


def test_research_identity_cannot_reuse_different_focus_or_scan_cache():
    from empire.plugins.data.preparation_cache import PreparationCache
    store = SimpleNamespace(prefix='test')
    original = scope()
    keys = {PreparationCache(store, 'v', s).key for s in (
        original, replace(original, focus='quality'), replace(original, scan='all'))}
    assert len(keys) == 3
