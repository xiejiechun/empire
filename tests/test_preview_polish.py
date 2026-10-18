"""Interaction counterexamples for the second preview refinement."""
import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QTabWidget, QWidget

from empire.plugins.ui.directory_panel import DirectoryPanel
from empire.plugins.ui.financial_statements import StatementPage
from empire.plugins.ui.listing_status import ListingStatusPage
from empire.plugins.ui.month_grid import MonthGrid
from empire.plugins.ui.preview_layout import DetailSplit
from empire.plugins.ui.series_chart import SeriesChart
from empire.plugins.ui.suspensions import SuspensionsPage
from tests.test_preview_redesign import dispose, shell


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_unknown_selected_day_survives_refresh_then_clears_on_month_change(app):
    grid = MonthGrid()
    grid.render('2026-10', {})
    grid.choose(grid.days.index('2026-10-04'))
    grid.render('2026-10', {})
    assert '2026-10-04' in grid.note.text() and '未取得该日证明' in grid.note.text()
    grid.render('2026-11', {})
    assert grid.active == '' and '2026-10-04' not in grid.note.text()
    dispose(grid, app)


def test_trade_page_source_sequence_is_used_by_axis_and_accessibility(app):
    chart = SeriesChart([dict(title='当前页价格', fields=[(1, '价格')], sequence=True)])
    chart.set_series([['09:30:00', 3], ['09:30:00', 4]], sequences=[400, 403])
    assert chart.canvases[0].domain() == [401, 404]
    chart.inspect(1)
    assert '来源序号 404' in chart.detail.text()
    assert '来源序号 404' in chart.canvases[0].accessibleDescription()
    dispose(chart, app)


def test_resizing_detail_moves_same_widget_without_duplicate_tabs(app):
    views, detail = QTabWidget(), QWidget()
    views.addTab(QWidget(), '方案')
    split = DetailSplit(views, detail)
    split.restore_view(1)  # Restored before the responsive detail tab exists.
    split.resize(600, 400)
    split.show()
    app.processEvents()
    assert views.currentWidget() is detail and views.count() == 2
    split.resize(1100, 400)
    app.processEvents()
    assert views.count() == 1 and split.widget(1) is detail
    split.resize(600, 400)
    app.processEvents()
    assert views.count() == 2 and views.currentWidget() is detail
    dispose(split, app)


def test_directory_refresh_requeries_and_preserves_business_identity(app):
    host, calls = shell()
    page = DirectoryPanel(host, 'sample.query', 'browse', 'id', ['id', 'name'], ['编号', '名称'])
    page.timer.stop()
    page.show()
    page.tick()
    calls[-1][1].set_result({'rows': [{'id': 'A', 'name': '甲'}, {'id': 'B', 'name': '乙'}], 'next': None})
    page.tick()
    page.table.selectRow(1)
    page.refresh()
    page.tick()
    calls[-1][1].set_result({'rows': [{'id': 'B', 'name': '乙新版'}, {'id': 'C', 'name': '丙'}], 'next': None})
    page.tick()
    assert len(calls) == 2 and page.table.item(page.table.currentRow(), 0).text() == 'B'
    assert page.table.item(page.table.currentRow(), 1).text() == '乙新版'
    dispose(page, app)


def test_narrow_suspension_keeps_records_visible_and_calendar_explicit(app):
    host, _ = shell()
    page = SuspensionsPage(host)
    page.timer.stop()
    page.resize(700, 600)
    page.show()
    app.processEvents()
    assert page.calendar_toggle.isVisible() and not page.calendar_sidebar.isVisible()
    page.calendar_toggle.setChecked(True)
    assert page.calendar_sidebar.isVisible()
    page.calendar_toggle.setChecked(False)
    page.resize(1100, 700)
    app.processEvents()
    assert page.calendar_sidebar.isVisible() and not page.calendar_toggle.isVisible()
    dispose(page, app)


def test_statement_one_result_hides_directory_but_can_expand(app):
    host, _ = shell()
    page = StatementPage(host, 'income')
    page.timer.stop()
    page.securities = [{'market': 'SZ', 'code': '000001', 'name': '证券'}]
    page.resize(700, 600)
    page.show()
    app.processEvents()
    page.fit_security_list()
    assert not page.table.isVisible() and page.directory_toggle.isVisible()
    page.directory_toggle.setChecked(True)
    assert page.table.isVisible()
    state = page.save_ui_state()
    assert state['directory_expanded'] is True
    dispose(page, app)


def test_listing_description_plain_text_and_empty_selection_cancels_old_request(app):
    host, calls = shell()
    page = ListingStatusPage(host)
    page.timer.stop()
    page.show()
    page.description.setText('<b>来源原文</b>')
    assert page.description.textFormat() == Qt.TextFormat.PlainText
    page.detail_future = page.scope.invoke('detail', host.runtime, 'sample', 'detail')
    page.selected()
    assert calls[-1][1].cancelled() and page.detail_future is None
    assert '没有所选事件' in page.description.text()
    dispose(page, app)
