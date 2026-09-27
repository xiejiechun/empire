import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.trade_calendar import TradeCalendarPage  # noqa: E402


class Runtime:
    def __init__(self):
        self.calls = []
        self.futures = []

    def invoke(self, *args):
        self.calls.append(args)
        value = Future()
        self.futures.append(value)
        return value


def test_calendar_month_changes_discard_stale_results_and_missing_is_not_closed():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    shell = SimpleNamespace(runtime=runtime, cfg={}, navigate=lambda _: None)
    page = TradeCalendarPage(shell)
    page.timer.stop()
    try:
        page.show()
        app.processEvents()
        page.set_month(2026, 9)
        page.tick()
        first_month = runtime.calls[0][-1]
        runtime.futures[0].set_running_or_notify_cancel()
        page.set_month(2027, 12)
        runtime.futures[0].set_result({"month": first_month, "rows": [], "complete": False})
        page.tick()
        assert runtime.calls[-1] == ("calendar.query", "month", "2027-12")
        runtime.futures[-1].set_result({"month": "2027-12", "complete": False, "rows": [
                {"trade_date": "2027-12-01", "is_trade": True, "updated_at": "2026-09-23T08:00:00"},
                {"trade_date": "2027-12-02", "is_trade": False, "updated_at": "2026-09-23T08:00:00"},
        ]})
        page.tick()
        assert page.table.rowCount() == 31
        assert page.table.item(0, 2).text() == "交易日"
        assert page.table.item(1, 2).text() == "休市"
        assert page.table.item(2, 2).text() == "未采集"
        assert "08:00" in page.table.item(0, 3).text()
        assert "2 / 31" in page.summary.text()
        assert not page.next.isEnabled()
        page.set_month(1990, 1)
        assert page.selected_month() == "1990-12"
        runtime.futures[-1].set_result({"month": "1990-12", "complete": False, "rows": []})
        page.tick()
        assert page.table.rowCount() == 13
        assert page.table.item(0, 0).text() == "1990-12-19"
        assert not page.previous.isEnabled()
        shell.shutting_down = True
        page.timer.start()
        page.tick()
        assert not page.timer.isActive()
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
