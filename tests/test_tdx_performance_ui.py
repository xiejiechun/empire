import os
from types import SimpleNamespace

import pytest

from empire.bootstrap import build_manager
from empire.contracts.tdx_performance import KINDS, identity, project
from empire.plugins.collectors.tdx_performance_source import parse
from tests.test_tdx_performance import source


@pytest.mark.parametrize('kind', KINDS)
def test_lazy_page_draft_navigation_and_lifecycle(kind):
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication

    from empire.contracts.ui import NavigationContext
    from empire.plugins.ui.tdx_performance import PerformanceUiPlugin
    app = QApplication.instance() or QApplication([])
    plugin = PerformanceUiPlugin(kind)
    contribution, = plugin.create_pages()
    assert contribution.id == kind and contribution.catalogued
    assert contribution.management.context.task_id == project(kind)
    page = contribution.factory(SimpleNamespace())
    rows, _ = parse(kind, source(kind), None if kind == 'holder_count' else '2026-06-30')
    for row in rows:
        row['record_key'] = identity(kind, row)
    page.resize(1100, 760)
    page.render(rows)
    page.code.setText('尚未提交')
    page.render(rows)
    assert page.code.text() == '尚未提交' and page.applied == ('', '', '')
    page.find()
    assert page.spec()[0] == '尚未提交'
    state = page.save_ui_state()
    page.code.clear()
    page.restore_ui_state(state)
    assert page.code.text() == '尚未提交'
    page.apply_navigation_context(NavigationContext(unified_code='000001.SZ'))
    assert page.applied[0] == '000001.SZ'
    page.timer.stop()
    page.scope.cancel_all()
    page.deleteLater()
    app.processEvents()


def test_five_independent_collectors_and_queries():
    manager = build_manager({'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}})
    collectors = []
    for kind in KINDS:
        collector = manager.entries['collector.tdx_' + kind].plugin
        assert collector.project_id == project(kind)
        assert manager.entries['data.tdx_' + kind].plugin.kind == kind
        collectors.append(collector)
    assert len({id(c) for c in collectors}) == 5
