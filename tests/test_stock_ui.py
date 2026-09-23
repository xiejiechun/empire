import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

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
                         "finished_at": "2026-09-22 12:00:00"},
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
        page.search.setText("银行")
        page.market.setCurrentIndex(page.market.findData("SZ"))
        runtime.futures[0].set_result(result([]))
        page.tick()
        assert runtime.calls[-1] == ("stocks.query", "list_stocks", "银行", 0, 200, "SZ")
        assert "匹配 0 条" not in page.result_summary.text()
        row = {"code": "000001", "name": "平安银行", "unified_code": "000001.SZ",
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
