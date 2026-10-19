"""Exercise Qt completion insertion, rather than calling the business slot directly."""
import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.features.kaipanla.product_page import ProductPage


def test_completion_keeps_bare_code_and_applies_recent_archived_day():
    app = QApplication.instance() or QApplication([])
    calls = []
    def invoke(*args):
        future = Future()
        calls.append((args, future))
        return future
    host = SimpleNamespace(cfg={}, shutting_down=False,
                           runtime=SimpleNamespace(invoke=invoke), navigate_management=lambda _: None)
    page = ProductPage(host, 'trend')
    page.timer.stop()
    page.candidates.poll.stop()
    try:
        page.show()
        page.code.setFocus()
        page.code.setText('000820')
        record = dict(unified_code='000820.SZ', name='神雾节能')
        label = '000820.SZ  神雾节能'
        page.candidates.options = {label: record}
        page.candidates.model.setStringList([label])
        page.candidates.completer.complete()
        app.processEvents()
        popup = page.candidates.completer.popup()
        index = popup.model().index(0, 0)
        QTest.mouseClick(popup.viewport(), Qt.MouseButton.LeftButton,
                         pos=popup.visualRect(index).center())
        app.processEvents()
        # Some completion paths insert the label after emitting activated.
        # Exercise that order too, before returning control to the event loop.
        page.candidates.completer.activated[str].emit(label)
        page.code.setText(label)
        app.processEvents()
        assert page.code.text() == '000820'
        assert calls[-1][0][1:4] == ('archived_date', 'SZ', '000820')
        calls[-1][1].set_result('2026-09-30')
        page.tick_date()
        assert page.day.date().toString('yyyy-MM-dd') == '2026-09-30'
        assert page.applied == ('SZ', '000820', '2026-09-30')
    finally:
        page.scope.close()
        page.candidates.scope.close()
        page.close()
        page.deleteLater()
        app.processEvents()
