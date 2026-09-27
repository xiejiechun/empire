import os
from concurrent.futures import Future
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel  # noqa: E402
from PySide6.QtWidgets import QApplication, QStatusBar  # noqa: E402

from empire.plugins.ui.stocks import StockListPage  # noqa: E402


class Runtime:
    def __init__(self):
        self.calls = []
        self.futures = []

    def snapshot(self):
        return {"plugins": [{"id": "data.stocks", "state": "RUNNING"}]}

    def invoke(self, *args):
        self.calls.append(args)
        future = Future()
        self.futures.append(future)
        return future


def result(rows):
    return {"snapshot": {"snapshot_id": "complete", "row_count": 5566,
                         "finished_at": "2026-09-22 20:00:00"},
            "total": len(rows), "rows": rows}


def test_new_market_query_discards_old_result_and_copy_keeps_leading_zero():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    status = QStatusBar()
    page = StockListPage(SimpleNamespace(runtime=runtime, cfg={}, statusBar=lambda: status))
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.tick()
        assert runtime.calls[-1] == ("stocks.query", "list_stocks", "", 0, 200, None)
        runtime.futures[0].set_running_or_notify_cancel()
        page.search.setText("银行")
        page.market.setCurrentIndex(page.market.findData("SZ"))
        runtime.futures[0].set_result(result([]))
        page.tick()
        assert runtime.calls[-1] == ("stocks.query", "list_stocks", "银行", 0, 200, "SZ")
        assert "匹配 0 条" not in page.result_summary.text()
        row = {"source": "sina", "code": "000001", "name": "平安银行", "unified_code": "000001.SZ",
               "market": "SZ", "source_symbol": "sz000001"}
        runtime.futures[-1].set_result(result([row]))
        page.tick()
        assert "匹配 1 条" in page.result_summary.text()
        assert "第 1 / 1 页" in page.page_label.text()
        assert "20:00:00" in page.status.text()
        page.table.selectRow(0)
        page.copy_selection()
        assert "000001\t平安银行\t000001.SZ\t深圳 (SZ)\tsz000001" in app.clipboard().text()
        page.clear_search()
        assert runtime.calls[-1] == ("stocks.query", "list_stocks", "", 0, 200, "SZ")
    finally:
        page.close()
        page.deleteLater()
        status.deleteLater()
        app.processEvents()


@pytest.fixture
def stock_page():
    app = QApplication.instance() or QApplication([])
    status = QStatusBar()
    page = StockListPage(SimpleNamespace(runtime=Runtime(), cfg={}, statusBar=lambda: status))
    page.timer.stop()
    page.resize(900, 600)
    page.show()
    app.processEvents()
    try:
        yield app, page
    finally:
        page.close()
        page.deleteLater()
        status.deleteLater()
        app.processEvents()


def stocks(count=100):
    return [{"source": "sina", "code": f"{number:06}", "name": f"股票{number}",
             "unified_code": f"{number:06}.SZ", "market": "SZ",
             "source_symbol": f"sz{number:06}"} for number in range(count)]


def select_rows(widget, selected, current):
    model = widget.selectionModel()
    for row in selected:
        model.select(widget.model().index(row, 0),
                     QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)
    widget.setCurrentCell(*current, QItemSelectionModel.SelectionFlag.NoUpdate)


def test_stock_refresh_keeps_multiple_identities_current_scroll_and_reuses_cells(stock_page):
    app, page = stock_page
    original = stocks()
    page.show_result(result(original))
    app.processEvents()
    select_rows(page.table, [20, 40], (55, 2))  # Current cell need not be selected.
    page.table.verticalScrollBar().setValue(15)
    cell = page.table.item(20, 1)
    updated = original[10:] + original[:10]
    updated[10] = {**updated[10], "name": "修订名称"}
    page.show_result(result(updated))
    assert page.table.item(20, 1) is cell
    assert {index.row() for index in page.table.selectedIndexes()} == {10, 30}
    assert (page.table.currentRow(), page.table.currentColumn()) == (45, 2)
    assert page.table.verticalScrollBar().value() == 15
    assert page.copy_button.isEnabled()
    page.copy_selection()
    assert app.clipboard().text().splitlines() == [
        "代码\t名称\t统一代码\t市场\t来源代码",
        "000020\t修订名称\t000020.SZ\t深圳 (SZ)\tsz000020",
        "000040\t股票40\t000040.SZ\t深圳 (SZ)\tsz000040",
    ]


def test_stock_refresh_removes_missing_selection_and_never_selects_same_code_other_source(stock_page):
    app, page = stock_page
    original = stocks(3)
    page.show_result(result(original))
    select_rows(page.table, [0, 1], (1, 2))
    updated = [original[0], {**original[1], "source": "other", "name": "其他来源"}, original[2]]
    page.show_result(result(updated))
    assert {index.row() for index in page.table.selectedIndexes()} == {0}
    assert page.table.currentRow() == -1
    page.copy_selection()
    assert "其他来源" not in app.clipboard().text()
    assert len(app.clipboard().text().splitlines()) == 2
    page.show_result(result(updated[1:]))
    assert not page.table.selectedIndexes()
    assert page.table.currentRow() == -1
    assert not page.copy_button.isEnabled()
    page.show_result(result([]))
    assert page.table.rowCount() == 0 and not page.copy_button.isEnabled()


def test_unchanged_verified_batch_does_not_poll_mysql_forever():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    runtime.snapshot = lambda: {"plugins": [
        {"id": "data.stocks", "state": "RUNNING"},
        {"id": "collector.sina_universe", "health": {"status": "complete", "snapshot_id": "verified"}},
    ]}
    status = QStatusBar()
    page = StockListPage(SimpleNamespace(runtime=runtime, cfg={}, statusBar=lambda: status))
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.tick()
        runtime.futures[-1].set_result({**result([]), "verified_snapshot_id": "verified"})
        page.tick()
        page.tick()
        assert len(runtime.calls) == 1
        assert page.previous_snapshot == "verified"
    finally:
        page.close()
        page.deleteLater()
        status.deleteLater()
        app.processEvents()


def test_stock_sync_submission_failure_is_rendered_and_can_retry():
    app = QApplication.instance() or QApplication([])

    class RecoveringRuntime(Runtime):
        def __init__(self):
            super().__init__()
            self.broken = True

        def invoke(self, *args):
            if self.broken:
                raise RuntimeError("service disappeared")
            return super().invoke(*args)

    runtime = RecoveringRuntime()
    status = QStatusBar()
    page = StockListPage(SimpleNamespace(runtime=runtime, cfg={}, statusBar=lambda: status))
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.tick()
        page.tick()
        assert "读取失败" in page.result_summary.text()
        assert page.future is None
        runtime.broken = False
        page.reload()
        runtime.futures[-1].set_result(result([]))
        page.tick()
        assert "匹配 0 条" in page.result_summary.text()
    finally:
        page.close()
        page.deleteLater()
        status.deleteLater()
        app.processEvents()


def test_stock_refresh_failure_marks_previous_rows_as_stale():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    status = QStatusBar()
    page = StockListPage(SimpleNamespace(runtime=runtime, cfg={}, statusBar=lambda: status))
    page.timer.stop()
    row = {"source": "sina", "code": "000001", "name": "平安银行",
           "unified_code": "000001.SZ", "market": "SZ", "source_symbol": "sz000001"}
    try:
        page.show()
        app.processEvents()
        page.tick()
        runtime.futures[-1].set_result(result([row]))
        page.tick()
        page.reload()
        runtime.futures[-1].set_exception(ConnectionError("offline"))
        page.tick()
        assert page.table.rowCount() == 1
        assert "当前刷新失败" in page.result_summary.text()
        assert "旧数据" in page.result_summary.text()
    finally:
        page.close()
        page.deleteLater()
        status.deleteLater()
        app.processEvents()
