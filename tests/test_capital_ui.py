import os
from types import SimpleNamespace

import pytest

from empire.bootstrap import build_manager
from empire.plugins.collectors.tdx_capital_source import parse
from empire.plugins.datasets.capital_actions import KINDS
from tests.capital_samples import source, with_issue_detail


@pytest.mark.parametrize('kind', list(KINDS))
def test_independent_lazy_page_query_and_draft_preservation(kind):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.capital_actions import CapitalUiPlugin
    app = QApplication.instance() or QApplication([])
    plugin = CapitalUiPlugin(kind)
    contributions = plugin.create_pages()
    assert len(contributions) == 1 and contributions[0].catalogued
    assert contributions[0].category == '增发送配'
    page = contributions[0].factory(SimpleNamespace(cfg={}, shutting_down=False))
    values = parse(kind, source(kind), 10000, '2025-12-31' if kind == 'dividends' else None)[0]
    page.render(values)
    if kind == 'additional_issues':
        assert '尚未补齐' in page.detail.toPlainText()
        with_issue_detail(values)
    page.code.setText('688')
    page.render(values)
    assert page.code.text() == '688'
    assert '来源未提供' in page.detail.toPlainText() or kind == 'dividends'
    assert '每股' in page.detail.toPlainText() or kind == 'additional_issues'
    if kind == 'additional_issues':
        assert '发行对象：符合条件的投资者' in page.detail.toPlainText()
        assert '实际募资总额（元）：600000' in page.detail.toPlainText()
        assert '增发上市首日收盘价（元）：12' in page.detail.toPlainText()
    page.timer.stop()
    page.deleteLater()
    app.processEvents()


def test_three_independent_collectors_datasets_and_queries_registered():
    manager = build_manager({'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}})
    ids = []
    for kind in KINDS:
        collector = manager.entries['collector.tdx_' + kind].plugin
        assert collector.manifest.provides == ('collector.tdx_' + kind,)
        assert collector.project_id == KINDS[kind][2]
        query = manager.entries['data.' + kind].plugin
        assert query.preparation[0].requirement == kind
        ids.append(id(collector))
    assert len(set(ids)) == 3
