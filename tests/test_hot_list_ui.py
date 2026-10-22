"""Lazy SQL page, stale reads, draft ownership and hidden cancellation."""

import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.features.hot_list.source import parse_detail  # noqa: E402
from empire.features.hot_list.ui import HotListPage, HotListUiPlugin  # noqa: E402
from tests.test_tdx_hot_list import CODE, DATE, detail  # noqa: E402


def test_lazy_drafts_stale_results_and_hidden_cancellation():
    app = QApplication.instance() or QApplication([])
    pending = []

    def invoke(*args):
        future = Future()
        pending.append((args, future))
        return future

    shell = SimpleNamespace(runtime=SimpleNamespace(invoke=invoke), cfg={})
    spec = HotListUiPlugin().create_pages()[0]
    assert spec.catalogued and spec.management.context.task_id == "tdx-hot-list"
    page = HotListPage(shell)
    head = dict(
        unified_code=CODE,
        list_date=DATE,
        directory_listed=True,
        detail_status="present",
        reason_count=1,
        seat_count=3,
    )
    try:
        assert not pending and not page.timer.isActive()
        page.show()
        app.processEvents()
        page.timer.stop()
        page.tick()
        page.code.setText("未提交草稿")
        pending[-1][1].set_result(dict(rows=[head], next=[DATE, CODE]))
        page.tick()
        assert page.code.text() == "未提交草稿"
        page.table.selectRow(0)
        page.tick()
        value = parse_detail(detail(shenzhen=True))
        value.update(
            unified_code=CODE,
            list_date=DATE,
            detail_status=value.pop("status"),
            version_observed_at="2026-03-03",
        )
        pending[-1][1].set_result(value)
        page.tick()
        assert "机构专用" in page.reader.toPlainText()
        state = page.save_ui_state()
        page.restore_ui_state(state)
        assert page.code.text() == "未提交草稿"
        page.code.setText("000001")
        page.find()
        assert not page.next.isEnabled() and not page.previous.isEnabled()
        page.move(True)
        assert page.after is None
        page.tick()
        in_flight = pending[-1][1]
        page.hide()
        assert in_flight.cancelled() and not page.timer.isActive()
        before = len(pending)
        page.tick()
        assert len(pending) == before
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
