"""Full-history candles, honest modes, viewport boundaries and retained-result identity."""
from concurrent.futures import Future
from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QApplication

from empire.features.adjustment.chart import AdjustmentChart
from empire.features.adjustment.ui import AdjustmentPage
from empire.plugins.ui.candlestick_chart import moving_average


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def history(size=650, problem=''):
    rows = []
    for i in range(size):
        values = dict(open=str(10+i*.01), high=str(11+i*.01), low=str(9+i*.01), close=str(10.5+i*.01))
        row = dict(date=(date(2024, 1, 1)+timedelta(days=i)).isoformat(), **values,
                   factor='1', forward_multiplier='.5', backward_multiplier='1', reference=None, events=[])
        row.update({prefix+k: None if problem else str(float(v)*factor)
                    for prefix, factor in (('forward_', .5), ('backward_', 1)) for k, v in values.items()})
        rows.append(row)
    return dict(rows=rows, security='600016.SH', base_date=rows[0]['date'], anchor_date=rows[-1]['date'],
                adjustment_problem=problem, limitations='当前归档', input_hash='sample')


def test_moving_averages_need_full_period_and_include_prices_before_viewport():
    assert moving_average([1, 2, 3, 4, 5, 6], 5) == [None, None, None, None, 3, 4]
    assert moving_average([1, 2, None, 4, 5, 6], 2) == [None, 1.5, None, None, 4.5, 5.5]


def test_invalid_raw_day_remains_visible_gap_without_price_or_bridged_average(app):
    panel = AdjustmentChart()
    result = history(size=30, problem='原始K线缺口：2024-01-11开盘价为零')
    for key in ('open', 'high', 'low', 'close'):
        result['rows'][10][key] = None
    panel.set_result(result)
    try:
        assert panel.canvas.count == 30 and panel.canvas.points[10]['date'] == '2024-01-11'
        assert panel.canvas.points[10]['close'] is None
        assert panel.canvas.averages[5][10:15] == [None]*5
        panel.canvas.inspect(10)
        assert '收 —' in panel.detail.text()
        panel.canvas.grab()
    finally:
        panel.deleteLater()


def test_candles_use_entire_query_and_explicit_zoom_pan_boundaries(app):
    panel = AdjustmentChart()
    try:
        panel.set_result(history())
        canvas = panel.canvas
        assert len(canvas.points) == canvas.count == 650
        assert canvas.points[-1]['date'] == panel.result['rows'][-1]['date']
        canvas.zoom(.5)
        assert canvas.count == 325
        for _ in range(10):
            canvas.pan(1)
        assert canvas.first == 325
        assert canvas.averages[5][canvas.first] is not None
        for _ in range(10):
            canvas.pan(-1)
        assert canvas.first == 0
        canvas.full_range()
        assert canvas.count == 650 and canvas.first == 0
        panel.mode.setCurrentIndex(1)
        assert canvas.points[0]['open'] == 5 and canvas.points[0]['high'] == 5.5
        panel.mode.setCurrentIndex(2)
        assert canvas.points[0]['open'] == 10
    finally:
        panel.deleteLater()


def test_missing_adjustment_never_draws_raw_as_adjusted(app):
    panel = AdjustmentChart()
    try:
        panel.set_result(history(problem='实施方案缺除权日期'))
        assert len(panel.canvas.points) == 650
        panel.mode.setCurrentIndex(1)
        assert not panel.canvas.points and '缺除权日期' in panel.canvas.message
        panel.mode.setCurrentIndex(0)
        assert len(panel.canvas.points) == 650
        panel.mark_stale('本次查询失败')
        assert '600016.SH' in panel.problem.text() and '上次结果' in panel.problem.text()
        panel.mode.setCurrentIndex(2)
        assert '本次查询失败' in panel.problem.text() and '上次结果' in panel.problem.text()
        panel.set_result(history())
        assert '本次查询失败' not in panel.problem.text()
    finally:
        panel.deleteLater()


def test_chart_keyboard_inspection_and_drag_keep_date_and_ohlc_identity(app):
    panel = AdjustmentChart()
    try:
        panel.resize(1000, 600)
        panel.show()
        panel.set_result(history())
        app.processEvents()
        canvas = panel.canvas
        canvas.zoom(.1)
        canvas.first = 100
        canvas.inspect(100)
        canvas.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Left, Qt.KeyboardModifier.NoModifier))
        assert canvas.hover == canvas.first == 99
        assert canvas.points[99]['date'] in panel.detail.text() and '高' in panel.detail.text()
        canvas.mousePressEvent(QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(500, 100),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        canvas.mouseMoveEvent(QMouseEvent(QEvent.Type.MouseMove, QPointF(650, 100),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier))
        assert canvas.first < 99
        image = canvas.grab().toImage()
        colors = {image.pixelColor(x, y).name() for x in range(76, image.width()-20, 2)
                  for y in range(16, image.height()-32, 2)}
        assert '#d4383a' in colors and '#fafbfd' in colors
    finally:
        panel.close()
        panel.deleteLater()


def test_table_pagination_does_not_truncate_or_reset_chart_and_drafts(app):
    pending = Future()
    page = AdjustmentPage(SimpleNamespace(runtime=SimpleNamespace(invoke=lambda *a: pending), cfg={}))
    try:
        page.find()
        pending.set_result(history())
        page.tick()
        page.chart.canvas.zoom(.5)
        page.turn(200)
        assert page.table.rowCount() == 200
        assert page.table.item(0, 0).text() == page.result['rows'][200]['date']
        assert len(page.chart.canvas.points) == 650 and page.chart.canvas.count == 325
        page.chart.mode.setCurrentIndex(1)
        state = page.save_ui_state()
        page.chart.mode.setCurrentIndex(0)
        page.restore_ui_state(state)
        assert page.chart.mode.currentIndex() == 1
    finally:
        page.scope.close()
        page.timer.stop()
        page.deleteLater()


def test_recreated_page_restores_applied_result_page_and_independent_draft(app):
    calls = []
    def invoke(*args):
        future = Future()
        calls.append((args, future))
        return future
    host = SimpleNamespace(runtime=SimpleNamespace(invoke=invoke), cfg={})
    page = AdjustmentPage(host)
    try:
        state = dict(market=1, code='600999', start='2026-01-01', end='2026-02-01',
                     applied=('SH', '600016', '2021-01-01', '2023-01-01'), offset=400, tab=1)
        page.restore_ui_state(state)
        assert calls[-1][0][-4:] == state['applied']
        calls[-1][1].set_result(history())
        page.tick()
        assert page.offset == 400 and page.table.item(0, 0).text() == page.result['rows'][400]['date']
        assert page.code.text() == '600999' and page.start.text() == '2026-01-01'
        assert page.result_spec == state['applied'] and page.tabs.currentIndex() == 1
    finally:
        page.scope.close()
        page.timer.stop()
        page.deleteLater()
