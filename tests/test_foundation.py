import asyncio
from concurrent.futures import Future

import pytest
from test_proxy_pool import Directory

from empire.plugins.infra.capacity import capacity
from empire.plugins.infra.http import RateGroup
from empire.plugins.infra.proxy_pool import ProxyPool


async def test_many_waiters_share_directory_refresh_and_cancel_cleanly():
    directory = Directory()
    directory.mapping.clear()
    calls = 0
    original = directory.eval

    async def counted(*args):
        nonlocal calls
        calls += 1
        return await original(*args)

    directory.eval = counted
    pool = ProxyPool(directory)
    tasks = [asyncio.create_task(pool.acquire()) for _ in range(50)]
    try:
        await asyncio.sleep(.15)
        baseline = calls
        assert baseline == 1
        await asyncio.sleep(.2)
        assert calls == baseline
        assert pool.waiting == 50
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await pool.close()
    assert pool.waiting == 0


def test_automatic_mode_has_no_implicit_global_gate():
    group = RateGroup("sina", ("sina.com.cn",), scaling_mode="auto", max_concurrency=64)
    result = capacity(group, 20)
    assert result["site_gate_interval_ms"] == 0
    assert result["rate_ceiling_rps"] == 10


def test_table_refresh_keeps_cell_and_scroll_position():
    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.common import rows, table
    app = QApplication.instance() or QApplication([])
    widget = table(["ID", "Count"])
    try:
        values = [[str(i), i] for i in range(100)]
        rows(widget, values)
        widget.resize(400, 300)
        widget.show()
        app.processEvents()
        widget.selectRow(20)
        widget.verticalScrollBar().setValue(15)
        cell = widget.item(20, 1)
        values[20][1] = 999
        rows(widget, values)
        assert widget.item(20, 1) is cell
        assert cell.text() == "999"
        assert widget.currentRow() == 20
        assert widget.verticalScrollBar().value() == 15
    finally:
        widget.close()


def test_query_scope_cancels_owned_reads():
    from PySide6.QtCore import QCoreApplication, QEvent
    from PySide6.QtWidgets import QApplication, QWidget

    from empire.plugins.ui.queries import QueryScope
    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    scope = QueryScope(widget)
    future = scope.track(Future())
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert future.cancelled()
    assert not scope.pending
    app.processEvents()


def test_query_scope_unifies_sync_failure_freshness_and_key_replacement():
    from types import SimpleNamespace

    from PySide6.QtWidgets import QApplication, QWidget

    from empire.plugins.ui.queries import QueryScope
    app = QApplication.instance() or QApplication([])
    widget = QWidget()
    scope = QueryScope(widget)

    class BrokenRuntime:
        def invoke(self, *args):
            raise RuntimeError("service disappeared")

    failed = scope.invoke("stocks", BrokenRuntime(), "stocks.query", "list_stocks")
    assert failed.done()
    with pytest.raises(RuntimeError, match="service disappeared"):
        scope.result("stocks", failed)
    assert scope.states["stocks"].phase == "error"

    first = Future()
    runtime = SimpleNamespace(invoke=lambda *args: first)
    assert scope.invoke("stocks", runtime, "stocks.query", "list_stocks") is first
    first.set_result({"rows": []})
    assert scope.result("stocks", first) == {"rows": []}
    assert scope.states["stocks"].last_success_at is not None

    stale = scope.failure_message("stocks", "读取失败", "offline", stale=True)
    assert "当前刷新失败" in stale and "成功读取的旧数据" in stale

    queued = Future()
    runtime.invoke = lambda *args: queued
    scope.invoke("stocks", runtime, "stocks.query", "list_stocks")
    replacement = Future()
    runtime.invoke = lambda *args: replacement
    scope.invoke("stocks", runtime, "stocks.query", "list_stocks")
    assert queued.cancelled() and not replacement.cancelled()
    widget.deleteLater()
    app.processEvents()


def test_table_selection_follows_device_identity_after_removal():
    from PySide6.QtWidgets import QApplication

    from empire.plugins.ui.common import rows, table
    app = QApplication.instance() or QApplication([])
    widget = table(["设备"])
    try:
        rows(widget, [["A"], ["B"]], keys=["a", "b"])
        widget.selectRow(1)
        rows(widget, [["B"]], keys=["b"])
        assert widget.currentRow() == 0 and widget.item(0, 0).text() == "B"
    finally:
        widget.close()
        app.processEvents()


def test_table_keyed_refresh_preserves_multi_selection_current_and_both_scrollbars():
    from PySide6.QtCore import QItemSelectionModel
    from PySide6.QtWidgets import QAbstractItemView, QApplication, QHeaderView

    from empire.plugins.ui.common import rows, table
    app = QApplication.instance() or QApplication([])
    widget = table(["ID", "Name", "Detail"])
    widget.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
    widget.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
    try:
        values = [[str(i), f"Name {i}", "detail"] for i in range(100)]
        keys = [("source", str(i)) for i in range(100)]
        rows(widget, values, keys=keys)
        widget.resize(300, 250)
        widget.show()
        app.processEvents()
        selection = widget.selectionModel()
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        selection.select(widget.model().index(30, 0), flags)
        selection.select(widget.model().index(50, 0), flags)
        widget.setCurrentCell(50, 2, QItemSelectionModel.SelectionFlag.NoUpdate)
        widget.verticalScrollBar().setValue(20)
        widget.horizontalScrollBar().setValue(50)
        horizontal = widget.horizontalScrollBar().value()
        assert horizontal > 0
        original = widget.item(20, 1)
        notifications = []
        widget.itemSelectionChanged.connect(lambda: notifications.append(
            ({i.row() for i in widget.selectedIndexes()}, widget.currentRow())))
        rows(widget, values[10:] + values[:10], keys=keys[10:] + keys[:10])
        assert widget.item(20, 1) is original
        assert {i.row() for i in widget.selectedIndexes()} == {20, 40}
        assert (widget.currentRow(), widget.currentColumn()) == (40, 2)
        assert widget.verticalScrollBar().value() == 20
        assert widget.horizontalScrollBar().value() == horizontal
        assert notifications == [({20, 40}, 40)]
        rows(widget, [["new", "Replacement", "detail"]], keys=[("other", "50")])
        assert not widget.selectedIndexes() and widget.currentRow() == -1
    finally:
        widget.close()
        app.processEvents()
