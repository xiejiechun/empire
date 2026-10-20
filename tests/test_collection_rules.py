import json
from copy import deepcopy
from pathlib import Path

import pytest

from empire.plugins.collection.rules import collection_rules, validate_rules, verify_registry
from empire.plugins.ui.collection_views.task_rules import rule_markdown
from scripts.documentation_contract import declarations

ROOT = Path(__file__).resolve().parents[1]


def test_rules_cover_real_registry_and_sql():
    manager, _, tasks = declarations(ROOT)
    coverage = json.loads((ROOT / 'docs/documentation-coverage.json').read_text(encoding='utf-8'))
    from empire.plugins.ui.help_content import topics
    verify_registry(manager, tasks, coverage['storage']['mysql'], topics())
    bad = dict(tasks)
    bad['new-unregistered-source'] = next(iter(tasks.values()))
    with pytest.raises(ValueError, match='覆盖'):
        verify_registry(manager, bad, coverage['storage']['mysql'], topics())


@pytest.mark.parametrize('field', ['initial', 'incremental', 'start', 'end', 'job_key', 'tables'])
def test_incomplete_rule_rejected(field):
    rules = deepcopy(collection_rules())
    rules['sina-news'][field] = ''
    with pytest.raises(ValueError):
        validate_rules(dict(schema=1, tasks=rules))


def test_request_contracts_match_real_source_parameters():
    from datetime import date

    from empire.features.kaipanla.contract import PRODUCTS
    from empire.features.kaipanla.product_source import options
    from empire.features.performance.source import params
    rules = collection_rules()
    for kind in ('earnings_forecast', 'earnings_quick', 'earnings_disclosure', 'earnings_report'):
        rule = rules['tdx-' + kind.replace('_', '-')]
        actual = params(kind, '2026-06-30')
        declared = rule['requests'][-1]['parameters']
        assert len(declared) == len(actual)
        for p, value in zip(declared, actual, strict=True):
            if p['value'] not in ('YYYY-MM-DD', '空字符串'):
                assert p['value'] == value
    for kind in PRODUCTS:
        request = rules['kaipanla-'+kind.replace('_','-')]['requests'][0]
        actual = options('000001', date(2026, 10, 13), kind)['data']
        declared = {p['name']: p['value'] for p in request['parameters']}
        assert set(declared) == set(actual)
        for key in ('c', 'a', 'apiv', 'PhoneOSNew', 'PhoneOS', 'VerSion'):
            assert declared[key] == actual[key]


def test_render_uses_current_namespace_without_exposing_credentials():
    text = rule_markdown(dict(id='sina-news', name='财经新闻'), dict(
        redis=dict(namespace='isolated:rules', password='REDIS_SECRET'),
        mysql=dict(database='rules_db', password='MYSQL_SECRET')))
    assert 'isolated:rules:ingest' in text
    assert 'isolated:rules:checkpoint:sina-news-v1' in text
    assert 'rules_db' in text and 'finance_news' in text
    assert 'SECRET' not in text
    assert '| 参数/位置 | 取值与设置方式 | 含义 |\n| ---' in text
    assert '当前第一页' in text and '上轮已归档ID' in text


def test_same_count_wrong_dataset_is_rejected():
    manager, _, tasks = declarations(ROOT)
    contribution = next(c for c in manager.entries['dataset.astock'].plugin.contributions
                        if 'sina-news' in c.projects.values())
    original = contribution.mapping.DATASETS
    contribution.mapping.DATASETS = {'incorrect.dataset'}
    try:
        from empire.plugins.ui.help_content import topics
        coverage = json.loads((ROOT / 'docs/documentation-coverage.json').read_text(encoding='utf-8'))
        with pytest.raises(ValueError, match='不一致'):
            verify_registry(manager, tasks, coverage['storage']['mysql'], topics())
    finally:
        contribution.mapping.DATASETS = original


def test_all_rules_render_without_network_and_keep_parameter_tables(monkeypatch):
    import os
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtGui import QFont, QFontDatabase, QTextTable
    from PySide6.QtWidgets import QApplication

    from empire.desktop.theme import STYLE
    from empire.plugins.ui.collection_views.task_rules import TaskRules
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/msyh.ttc')
    QFontDatabase.addApplicationFont('C:/Windows/Fonts/segoeui.ttf')
    pane = TaskRules()
    pane.setFont(QFont('Microsoft YaHei', 10))
    pane.setStyleSheet(STYLE)
    pane.resize(520, 600)
    pane.show()
    try:
        for ident, rule in collection_rules().items():
            pane.show_job(dict(id=ident, name=ident), {})
            app.processEvents()
            text = pane.browser.toPlainText()
            assert rule['job_key'] in text
            assert all(table in text for table in rule['tables'])
            assert pane.chapters.count() >= 12
            if any(r['parameters'] for r in rule['requests']):
                assert any(isinstance(f, QTextTable) for f in pane.browser.document().rootFrame().childFrames())
        pane.show_job(dict(id='tdx-unlocks', name='大小非解禁'), {})
        app.processEvents()
        pane.grab().save(str(ROOT / 'build/collection-rules-narrow.png'))
    finally:
        pane.close()
