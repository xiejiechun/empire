"""View membership and restored drafts must not imply business acceptance."""
from concurrent.futures import Future
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from empire.features.preparation.query import PreparationPlugin
from empire.features.preparation.ui import PreparationPage
from empire.features.stocks.query import StockDataPlugin


@pytest.fixture
def pages(monkeypatch):
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    app = QApplication.instance() or QApplication([])
    owned = []
    yield owned
    for page in owned:
        page.query_scope.close()
        page.deleteLater()
    app.processEvents()


async def test_directory_keeps_registered_missing_data_out_of_planned(pages):
    plugin = PreparationPlugin([StockDataPlugin.preparation[0]])
    await plugin.start(SimpleNamespace(optional=lambda _: None))
    report = await plugin.report()
    page = PreparationPage(SimpleNamespace(cfg={}, shutting_down=False))
    pages.append(page)
    page.timer.stop()
    page.render(report)
    page.directory.view.setCurrentIndex(page.directory.view.findData('available'))
    assert [e['id'] for e in page.visible_entries] == ['universe']
    assert not page.visible_entries[0]['assessment']['usable']
    page.directory.view.setCurrentIndex(page.directory.view.findData('planned'))
    assert 'universe' not in [e['id'] for e in page.visible_entries]
    page.search.setText('NO-SUCH-DATA')
    assert not page.detail.entry and not page.manage.isEnabled()
    assert '显示 0 /' in page.directory.count.text()


async def test_directory_restores_scope_and_selection_across_reports(pages):
    plugin = PreparationPlugin([])
    await plugin.start(SimpleNamespace(optional=lambda _: None))
    report = await plugin.report()
    shell = SimpleNamespace(cfg={}, shutting_down=False)
    page = PreparationPage(shell)
    pages.append(page)
    page.timer.stop()
    page.render(report)
    page.directory.view.setCurrentIndex(page.directory.view.findData('planned'))
    page.table.selectRow(1)
    selected = page.detail.entry['id']
    page.scope_toggle.setChecked(True)
    page.scope_bar.codes.setText('600000,000001')
    state = page.save_ui_state()
    restored = PreparationPage(shell)
    pages.append(restored)
    restored.timer.stop()
    restored.restore_ui_state(state)
    restored.render(report)
    assert restored.detail.entry['id'] == selected
    assert restored.scope_bar.codes.text() == '600000,000001'
    assert restored.scope_toggle.isChecked()
    assert restored.directory.view.currentData() == 'planned'
    restored.render(report)
    assert restored.detail.entry['id'] == selected
    assert restored.scope_bar.codes.text() == '600000,000001'


async def test_opening_only_reads_overview_and_scope_edits_do_not_scan(pages):
    calls = []
    pending = Future()
    def invoke(*args):
        calls.append(args)
        return pending
    plugin = PreparationPlugin([])
    await plugin.start(SimpleNamespace(optional=lambda _: None))
    report = await plugin.overview(dict(study='value', focus='operating', scan='research'))
    page = PreparationPage(SimpleNamespace(cfg={}, shutting_down=False, runtime=SimpleNamespace(invoke=invoke)))
    pages.append(page)
    page.timer.stop()
    page.show()
    page.tick()
    assert calls[0][1] == 'overview' and page.scope_bar.request()['codes'] == []
    pending.set_result(report)
    page.tick()
    assert page.table.rowCount() == 5
    page.scope_bar.codes.setText('600000')
    page.scope_bar.purpose.setCurrentIndex(page.scope_bar.purpose.findData('factor'))
    page.tick()
    assert len(calls) == 1 and '尚未重新检查' in page.summary.text()
    assert '固定样本' in page.research_conditions.toPlainText() or '当前版本' in page.research_conditions.toPlainText()


def test_shared_collector_opens_the_selected_business_page(pages):
    from empire.features.holders.ui import HolderUiPlugin
    contributions = [p for kind in ('top_holders', 'float_holders', 'bond_holders')
                     for p in HolderUiPlugin(kind).create_pages()]
    page = PreparationPage(SimpleNamespace(cfg={}, runtime=SimpleNamespace(page_contributions=lambda: contributions)))
    pages.append(page)
    page.timer.stop()
    project = contributions[0].management.context.task_id
    for kind in ('top_holders', 'float_holders', 'bond_holders'):
        assert page.data_page(dict(id=kind, project=project)) == kind
    assert page.data_page(dict(id='unrelated', project=project)) == ''
