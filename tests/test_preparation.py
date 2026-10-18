import os
from dataclasses import replace
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empire.bootstrap import build_manager
from empire.contracts.preparation import CheckEvidence
from empire.contracts.preparation_catalog import BY_ID, REQUIREMENTS
from empire.core.preparation_release import test_evidence as evidence_for_tests
from empire.core.time import CHINA
from empire.plugins.data.preparation import PreparationPlugin
from empire.plugins.data.preparation_checks import audit_calendar, audit_stocks, freshness
from empire.plugins.data.stocks import StockDataPlugin
from empire.plugins.datasets.trade_calendar import month_dates

CFG = {'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}}


def contribution(**changes):
    return replace(StockDataPlugin.preparation[0], **changes)


@pytest.fixture(autouse=True)
def no_external_test_artifact(monkeypatch):
    monkeypatch.setattr('empire.plugins.data.preparation.load_evidence', lambda: ({}, '未执行本版本测试'))


async def test_partial_and_invalid_evidence_never_finishes():
    service = SimpleNamespace(preparation_check=AsyncMock(return_value=(CheckEvidence('keys', 'pass', '去重通过'),)))
    registry = {'stocks.query': service}
    plugin = PreparationPlugin([contribution()])
    await plugin.start(SimpleNamespace(optional=registry.get))
    row = (await plugin.report())['rows'][0]
    assert row['data'] == 1 and not row['complete'] and row['development'] == 0
    assert all(c['status'] == 'unknown' for c in row['checks'] if c['phase'] == '数据' and c['id'] != 'keys')
    for invalid in (True, (CheckEvidence('unknown', 'pass', 'x'),),
                    (CheckEvidence('keys', 'pass', 'x'), CheckEvidence('keys', 'pass', 'y'))):
        service.preparation_check.return_value = invalid
        row = (await plugin.report())['rows'][0]
        assert row['data'] == 0 and not row['complete']


async def test_failure_and_stopped_plugin_revoke_previous_pass():
    service = SimpleNamespace(preparation_check=AsyncMock(return_value=(CheckEvidence('keys', 'pass', '通过'),)))
    registry = {'stocks.query': service}
    plugin = PreparationPlugin([contribution()])
    await plugin.start(SimpleNamespace(optional=registry.get))
    assert (await plugin.report())['rows'][0]['data'] == 1
    service.preparation_check.side_effect = RuntimeError('password=secret')
    row = (await plugin.report())['rows'][0]
    assert row['data'] == 0 and 'secret' not in str(row)
    registry.clear()
    row = (await plugin.report())['rows'][0]
    assert row['data'] == 0 and not row['running']


async def test_sources_cannot_pool_partial_passes():
    registry = {
        'stocks.query': SimpleNamespace(preparation_check=AsyncMock(return_value=(CheckEvidence('keys', 'pass', 'x'),))),
        'second.query': SimpleNamespace(preparation_check=AsyncMock(return_value=(CheckEvidence('fields', 'pass', 'x'),))),
    }
    plugin = PreparationPlugin([contribution(), contribution(capability='second.query', source='第二来源')])
    await plugin.start(SimpleNamespace(optional=registry.get))
    row = (await plugin.report())['rows'][0]
    assert row['data'] == 1 and len(row['providers']) == 2 and not row['complete']


@pytest.mark.parametrize('extra_source', [False, True])
async def test_one_source_passes_without_corroboration(monkeypatch, extra_source):
    requirement = BY_ID['suspensions']
    evidence = tuple(CheckEvidence(c.id, 'pass', '单一来源，声明区间已采齐；可选信息未提供')
                     for c in requirement.criteria)
    good = contribution(requirement='suspensions', capability='suspensions.query', source='单一来源')
    contributions = [good]
    registry = {'suspensions.query': SimpleNamespace(preparation_check=AsyncMock(return_value=evidence))}
    if extra_source:
        contributions.append(replace(good, capability='other.query', source='另一来源', project_id='other'))
        registry['other.query'] = SimpleNamespace(preparation_check=AsyncMock(side_effect=RuntimeError('不可用')))
    plugin = PreparationPlugin(contributions)
    await plugin.start(SimpleNamespace(optional=registry.get))
    monkeypatch.setattr(plugin, 'development', lambda *args: [dict(
        id='task', phase='开发', status='pass', measured='功能已验证')])
    row = next(r for r in (await plugin.report())['rows'] if r['id'] == 'suspensions')
    assert row['complete'] and row['source'] == '单一来源' and not row['blockers']
    assert row['data'] == 6
    # Optional information must not hide an actual gap inside the declared scope.
    registry['suspensions.query'].preparation_check.return_value = tuple(
        CheckEvidence(e.criterion, 'fail', '声明范围内漏页') if e.criterion == 'coverage' else e for e in evidence)
    row = next(r for r in (await plugin.report())['rows'] if r['id'] == 'suspensions')
    assert not row['complete']


async def test_registration_is_separate_from_execution_and_missing_tests():
    manager = build_manager(CFG)
    plugin = manager.entries['data.preparation'].plugin
    await plugin.start(SimpleNamespace(optional=lambda cap: None))
    row = (await plugin.report())['rows'][0]
    assert row['development'] == 3 and row['data'] == 0 and not row['complete']
    assert '未执行' in row['checks'][3]['measured']


def test_catalog_is_detailed_unique_and_acyclic():
    assert len(REQUIREMENTS) >= 35
    assert len(BY_ID) == len(REQUIREMENTS)
    for requirement in REQUIREMENTS:
        assert all((requirement.grain, requirement.fields, requirement.key, requirement.coverage, requirement.cadence))
        assert len(requirement.criteria) == 6
        assert len({c.id for c in requirement.criteria}) == 6
        def visit(ident, seen):
            assert ident not in seen
            for dependency in BY_ID[ident].dependencies:
                visit(dependency, seen | {ident})
        visit(requirement.id, set())


def test_catalog_rejects_bad_contributions():
    with pytest.raises(ValueError):
        PreparationPlugin([contribution(), contribution()])
    with pytest.raises(ValueError):
        PreparationPlugin([contribution(requirement='absent')])


def test_source_tests_need_real_pass_not_skip_or_other_suite():
    value = {'checked_at': 'now', 'cases': [{'module': 'tests.test_sina_universe', 'name': 'test_x', 'status': 'skipped'}]}
    assert not evidence_for_tests(value, ('tests/test_sina_universe.py',))[0]
    value['cases'][0]['status'] = 'passed'
    assert evidence_for_tests(value, ('tests/test_sina_universe.py',))[0]
    assert not evidence_for_tests(value, ('tests/test_sina_news.py',))[0]
    assert not evidence_for_tests(value, ())[0]


def test_stock_counts_alone_do_not_pass_identifiers_or_market_coverage():
    now = datetime(2026, 9, 28, tzinfo=CHINA)
    records = [{'code': '600000', 'source_symbol': 'sh600000', 'unified_code': '600000.SH', 'market': 'SH', 'name': '示例'}]
    state = {'publication': {'row_count': 1, 'snapshot_id': 'x', 'finished_at': now.isoformat()},
             'progress': {'finished_at': now.isoformat()}}
    result = {c.criterion: c for c in audit_stocks(records, state, now)}
    assert result['fields'].status == 'pass'
    assert result['coverage'].status == 'fail'  # SZ/BJ missing despite matching publication count.
    records[0]['unified_code'] = '600000.SZ'
    assert next(c for c in audit_stocks(records, state, now) if c.criterion == 'quality').status == 'fail'


def test_calendar_same_count_with_missing_date_fails(monkeypatch):
    monkeypatch.setattr('empire.plugins.data.preparation_checks.months_between', lambda a, b: ['2026-09'])
    records = [{'trade_date': d, 'is_trade': 1} for d in month_dates('2026-09')]
    now = datetime(2026, 9, 28, tzinfo=CHINA)
    state = {'observed': {'2026-09': now.isoformat()}}
    assert all(c.status == 'pass' for c in audit_calendar(records, state, now))
    records[0]['trade_date'] = month_dates('2026-08')[0]
    result = {c.criterion: c for c in audit_calendar(records, state, now)}
    assert result['coverage'].status == 'fail' and '2026-09' in result['coverage'].measured
    records[1]['is_trade'] = 2
    assert next(c for c in audit_calendar(records, state, now) if c.criterion == 'quality').status == 'fail'


def test_old_sql_upper_bound_and_future_timestamp_are_not_fresh():
    now = datetime(2026, 9, 28, tzinfo=CHINA)
    assert freshness('2026-09-01T00:00:00+08:00', now, 'SQL').status == 'unknown'
    assert freshness('2027-09-01T00:00:00+08:00', now, 'SQL').status == 'fail'
    assert freshness('2026-09-28', now, 'SQL').status == 'fail'
    assert freshness(None, now, 'SQL').status == 'unknown'


async def test_ui_filters_detail_selection_and_lifecycle():
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication

    from empire.desktop.page_lifecycle import activate_page, deactivate_page
    from empire.plugins.ui.preparation import PreparationUiPlugin
    app = QApplication.instance() or QApplication([])
    plugin = PreparationPlugin([])
    await plugin.start(SimpleNamespace(optional=lambda cap: None))
    report = await plugin.report()
    page = PreparationUiPlugin().create_pages()[0].factory(SimpleNamespace(cfg={}, shutting_down=False))
    activate_page(page)
    page.render(report)
    assert page.table.rowCount() == len(REQUIREMENTS)
    page.kind.setCurrentIndex(page.kind.findData('采集'))
    assert page.table.rowCount() == sum(r.kind == '采集' for r in REQUIREMENTS)
    page.kind.setCurrentIndex(0)
    assert page.table.rowCount() == len(REQUIREMENTS)
    page.table.selectRow(1)
    page.render(report)
    assert page.table.currentRow() == 1
    assert '交易日历' in page.detail.specification.toPlainText()
    assert page.detail.table.rowCount() == 12
    page.search.setText('分红送转')
    assert page.table.rowCount() == 1
    page.search.setText('历史停复牌')
    assert page.table.rowCount() == 1
    description = page.detail.specification.toPlainText()
    assert '必需信息' in description and '可选信息（缺少不影响本项通过）' in description
    assert '不要求多个网站相互印证' in description
    assert '公告' not in BY_ID['suspensions'].fields
    assert '公告' in BY_ID['suspensions'].optional_fields
    for removed in ('退市整理期', '每日涨停价和跌停价', '总股本和流通股本记录', '来源公布的自由流通股本',
                    '财经新闻', 'ETF', '逐笔委托'):
        page.search.setText(removed)
        assert page.table.rowCount() == 0
    for retained in ('股东户数', '个股融资交易和余额', '大单净额走势'):
        page.search.setText(retained)
        assert page.table.rowCount() == 1
    page.search.setText('NO-SUCH-DATA')
    assert page.table.rowCount() == 0 and not page.detail.entry
    page.search.clear()
    assert page.table.rowCount() == len(REQUIREMENTS)
    deactivate_page(page)
    assert not page.timer.isActive()
    page.deleteLater()
    app.processEvents()

def test_changed_source_or_corrupt_artifact_cannot_pass(tmp_path):
    import json

    from empire.core.preparation_release import load_evidence, source_digest
    for name in ('requirements.lock', 'pyproject.toml', 'Empire.spec', 'build.ps1', 'verify-release.ps1'):
        (tmp_path / name).write_text('original', encoding='utf-8')
    source = tmp_path / 'src/example.py'
    source.parent.mkdir()
    source.write_text('x=1', encoding='utf-8')
    target = tmp_path / 'build/generated/preparation-release.json'
    target.parent.mkdir(parents=True)
    payload = dict(schema=1, passed=True, source_sha256=source_digest(tmp_path), checked_at='now',
                   cases=[dict(module='tests.example', name='test_x', status='passed')])
    target.write_text(json.dumps(payload), encoding='utf-8')
    assert load_evidence(tmp_path)[0]
    source.write_text('x=2', encoding='utf-8')
    assert not load_evidence(tmp_path)[0]
    payload['cases'] = ['broken']
    target.write_text(json.dumps(payload), encoding='utf-8')
    assert not load_evidence(tmp_path)[0]


async def test_dependencies_block_completion_even_when_own_checks_pass(monkeypatch):
    plugin = PreparationPlugin([contribution(requirement='adjusted_prices')])
    await plugin.start(SimpleNamespace(optional=lambda cap: None))
    async def synthetic(requirement, c, artifact, error):
        checks = [{'id': 'x', 'phase': '数据', 'title': 'x', 'expected': 'x', 'action': 'x',
                   'status': 'pass' if requirement.id == 'adjusted_prices' else 'unknown', 'measured': 'x'}]
        return {'source': 'x', 'checks': checks, 'running': False, 'project': ''}
    monkeypatch.setattr(plugin, 'provider_report', synthetic)
    row = next(r for r in (await plugin.report())['rows'] if r['id'] == 'adjusted_prices')
    assert row['own_complete'] and not row['complete'] and row['blockers']


def test_stock_sql_wall_clock_is_beijing_without_double_conversion():
    now = datetime(2026, 9, 28, 12, tzinfo=CHINA)
    result = freshness('2026-09-28T11:00:00', now, 'SQL', naive_china=True)
    assert result.status == 'pass' and '11:00:00+08:00' in result.measured


def test_collection_projects_have_independent_boundaries():
    assert all(not r.dependencies and r.boundary for r in REQUIREMENTS if r.kind == '采集')
    for ident in ('index_members', 'index_weights', 'earnings_forecast', 'earnings_quick',
                  'pledge', 'freeze', 'financing', 'short_lending', 'margin_targets'):
        assert ident in BY_ID and BY_ID[ident].boundary
    assert BY_ID['market_value'].kind == '计算'
    assert {'historical_quote'} == set(BY_ID['market_value'].dependencies)
    assert {'income', 'balance', 'cashflow'} == set(BY_ID['financial_reconciliation'].dependencies)


def test_one_project_cannot_claim_two_independent_collection_outputs():
    with pytest.raises(ValueError, match='一个采集项目'):
        PreparationPlugin([contribution(), contribution(requirement='historical_quote', capability='prices.query')])


def test_explicit_same_response_preserves_separate_quality_checks():
    first = contribution(requirement='top_holders', project_id='ths-holders',
                         collector='collector.ths_holders', dataset='holders.reports',
                         response_group='holders.reports')
    second = replace(first, requirement='float_holders', capability='float_holders.query')
    assert len(PreparationPlugin([first, second]).contributions) == 2
    for changed in (replace(second, dataset='other'), replace(second, collector='collector.other'),
                    replace(second, job_key='other'), replace(second, source='other')):
        with pytest.raises(ValueError):
            PreparationPlugin([first, changed])


async def test_scope_removes_unrelated_preparation_but_preserves_news_service():
    manager = build_manager(CFG)
    plugin = manager.entries['data.preparation'].plugin
    await plugin.start(SimpleNamespace(optional=lambda cap: None))
    result = {r['id']: r for r in (await plugin.report())['rows']}
    assert 'news' not in result
    assert 'data.news' in manager.entries and 'collector.sina_news' in manager.entries
    assert callable(manager.entries['data.news'].plugin.list_news)
    assert all(c.requirement in result for c in plugin.contributions)
    assert not any(c.requirement == 'news' for c in plugin.contributions)
    assert {'pe', 'pb', 'ps', 'dividend_yield', 'financial_reconciliation'} <= result.keys()


def test_backtest_valuation_scope_keeps_strategy_factors_and_dependencies():
    removed = set('share_capital free_float daily_limits delisting_periods news news_history news_revisions news_stocks announcement_index '
                  'announcement_files announcement_text gdp cpi ppi pmi money_supply credit credit_stock '
                  'etf_catalog etf_nav etf_shares etf_pcf fx tick_trades tick_orders'.split())
    assert removed.isdisjoint(BY_ID)
    assert {'top_holders', 'float_holders', 'holder_count', 'large_order_trend', 'minute_entrust',
            'financing', 'short_lending', 'market_financing', 'market_short_lending', 'margin_targets',
            'connect_holdings', 'connect_trades', 'block_trades', 'hot_list', 'hot_list_summary',
            'rates', 'historical_quote', 'index_prices', 'index_members', 'index_weights'} <= BY_ID.keys()
    for item in REQUIREMENTS:
        assert set((*item.dependencies, *item.related)) <= BY_ID.keys()


async def test_independent_collection_does_not_wait_for_related_datasets(monkeypatch):
    plugin = PreparationPlugin([contribution(requirement='historical_quote')])
    await plugin.start(SimpleNamespace(optional=lambda cap: None))
    async def synthetic(requirement, c, artifact, error):
        return dict(source='x', running=False, project='', checks=[{
            'id': 'x', 'phase': '数据', 'title': 'x', 'expected': 'x', 'action': 'x',
            'status': 'pass' if requirement.id == 'historical_quote' else 'unknown', 'measured': 'x'}])
    monkeypatch.setattr(plugin, 'provider_report', synthetic)
    result = {r['id']: r for r in (await plugin.report())['rows']}
    assert result['historical_quote']['complete'] and not result['historical_quote']['blockers']
    assert not BY_ID['historical_quote'].dependencies
    assert not result['daily_reconciliation']['complete']


def test_retired_combined_projects_are_not_registered():
    retired = {'daily_prices', 'security_history', 'boards', 'adjustments', 'benchmark', 'risk_status',
               'price_limits', 'trading_rules', 'rights', 'valuation', 'earnings',
               'membership', 'announcements', 'holders', 'unlock', 'margin', 'connect',
               'large_trades', 'ticks', 'macro', 'etf'}
    assert not retired.intersection(BY_ID)


@pytest.mark.parametrize('same_capability', [True, False])
def test_independent_projects_require_independent_collector_plugins(same_capability):
    first = contribution(requirement='dividends', project_id='dividends', collector='collect.dividends')
    second = contribution(requirement='additional_issues', project_id='issues', capability='issues.query',
                          collector='collect.dividends' if same_capability else 'collect.issues')
    provider = SimpleNamespace(manifest=SimpleNamespace(provides=(first.collector, second.collector)))
    with pytest.raises(ValueError, match='独立采集插件'):
        PreparationPlugin([first, second], [provider])
    second = replace(second, collector='collect.issues')
    providers = [SimpleNamespace(manifest=SimpleNamespace(provides=(c.collector,))) for c in (first, second)]
    PreparationPlugin([first, second], providers)


async def test_independent_company_actions_and_catalog_visible_in_ui(monkeypatch):
    plugin = PreparationPlugin([])
    await plugin.start(SimpleNamespace(optional=lambda cap: None))
    async def synthetic(requirement, c, artifact, error):
        return dict(source='test', running=False, project='', checks=[dict(
            id='temporal', phase='数据', title='日期', expected='日期', action='检查',
            status='pass' if requirement.id == 'dividends' else 'unknown', measured='检查')])
    monkeypatch.setattr(plugin, 'provider_report', synthetic)
    report = await plugin.report()
    result = {r['id']: r for r in report['rows']}
    assert result['dividends']['complete']
    assert not result['additional_issues']['complete'] and not result['rights_issues']['complete']
    for ident in ('financing', 'market_financing', 'short_lending', 'market_short_lending',
                  'hot_list', 'hot_list_summary', 'large_order_trend', 'holder_count'):
        assert ident in result and not result[ident]['blockers']
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.preparation import PreparationPage
    app = QApplication.instance() or QApplication([])
    page = PreparationPage(SimpleNamespace(cfg={}, shutting_down=False))
    page.render(report)
    for name in ('分红送转', '增发', '配股'):
        page.search.setText(name)
        assert page.table.rowCount() == 1
        assert name in page.detail.specification.toPlainText()
    page.search.setText('分红送转')
    text = page.detail.specification.toPlainText()
    assert '含税' in text and '除权除息日作为现金支付/记账日' in text
    assert '独立现金到账日期' in BY_ID['dividends'].optional_fields
    page.timer.stop()
    page.deleteLater()
    app.processEvents()


@pytest.mark.parametrize('value', [dict(codes=['bad']), dict(start='2025-1-1'), dict(start='2025-12-31', end='2025-01-01'), dict(purpose='guess')])
def test_preparation_scope_rejects_invalid_requests(value):
    from empire.contracts.preparation_scope import PreparationScope
    with pytest.raises(ValueError):
        PreparationScope.parse(value)


def test_readiness_separates_source_quality_and_use_limitations():
    from empire.plugins.data.preparation_results import summarize
    checks = [dict(id=k, phase='数据', status='pass', blocking=True) for k in ('keys','coverage','fields','quality','freshness')]
    checks.append(dict(id='temporal', phase='数据', status='fail', blocking=False))
    result = summarize(checks)
    assert result['integrity'] == '通过' and result['quality'] == '通过'
    assert result['usage'] == '有限制' and result['use_state'] == '可用（有限制）'
    checks[-1]['blocking'] = True
    assert summarize(checks)['use_state'] == '不可用'
    checks[-1]['blocking'] = False
    checks[2]['status'] = 'fail'
    result = summarize(checks)
    assert result['integrity'] == '通过' and result['quality'] == '有异常' and not result['usable']


async def test_checker_cannot_hide_integrity_failure_as_limitation():
    from empire.plugins.data.financial_statements import FinancialDataPlugin
    c = FinancialDataPlugin('income').preparation[0]
    service = SimpleNamespace(preparation_check=AsyncMock(return_value=(CheckEvidence('coverage','fail','missing',blocking=False),)))
    plugin = PreparationPlugin([c])
    await plugin.start(SimpleNamespace(optional=lambda cap: service if cap == 'income.query' else None))
    result = await plugin.report(dict(codes=['601139']))
    row = next(r for r in result['rows'] if r['id'] == 'income')
    assert not row['assessment']['usable'] and all(x['status'] == 'unknown' for x in row['checks'] if x['phase'] == '数据')

@pytest.mark.parametrize('declared,purpose,criterion,status,allowed', [
    (True, 'analysis', 'quality', 'fail', True),
    (False, 'analysis', 'quality', 'fail', False),
    (True, 'historical_signal', 'quality', 'fail', False),
    (True, 'analysis', 'coverage', 'fail', False),
    (True, 'analysis', 'fields', 'fail', False),
    (True, 'analysis', 'quality', 'unknown', False),
])
async def test_only_declared_analysis_source_quality_can_be_a_limitation(declared, purpose, criterion, status, allowed):
    from empire.plugins.data.holders import HolderDataPlugin
    c = replace(HolderDataPlugin('top_holders').preparation[0], analysis_quality_limits=declared)
    service = SimpleNamespace(preparation_check=AsyncMock(return_value=tuple(
        CheckEvidence(k.id, status if k.id == criterion else 'pass', '来源限制或集合证据', blocking=k.id != criterion)
        for k in BY_ID['top_holders'].criteria)))
    plugin = PreparationPlugin([c])
    await plugin.start(SimpleNamespace(optional=lambda cap: service if cap == c.capability else None))
    report = await plugin.report(dict(codes=['601139'], purpose=purpose))
    row = next(r for r in report['rows'] if r['id'] == 'top_holders')
    assert row['assessment']['usable'] == allowed
    if allowed:
        assert row['assessment']['integrity'] == '通过'
        assert row['assessment']['quality'] == '有限制'
    else:
        assert all(x['status'] == 'unknown' for x in row['checks'] if x['phase'] == '数据')
