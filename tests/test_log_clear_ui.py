import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from PySide6.QtWidgets import QApplication, QComboBox, QMessageBox  # noqa: E402

from empire.plugins.ui.log_clear import LogClearBar  # noqa: E402


def test_confirmation_scope_pending_switch_and_failure(monkeypatch):
    app = QApplication.instance() or QApplication([])
    selector = QComboBox()
    selector.addItem('全部项目', '*')
    selector.addItem('股票', 'stocks')
    calls, refreshed, messages = [], [], []
    future = Future()
    def invoke(*args):
        calls.append(args)
        return future
    shell = SimpleNamespace(runtime=SimpleNamespace(invoke=invoke), cfg={})
    bar = LogClearBar(shell, selector, '错误记录', 'collection.records', 'clear_logs',
        lambda project: ('errors', project), lambda: refreshed.append(True))
    bar.timer.stop()
    def confirm(*args):
        messages.append(args[2])
        return QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, 'question', confirm)
    bar.clear()
    assert not calls and '全部项目' in messages[-1]
    monkeypatch.setattr(QMessageBox, 'question', lambda *args: QMessageBox.StandardButton.Yes)
    selector.setCurrentIndex(1)
    bar.clear()
    assert calls == [('collection.records', 'clear_logs', 'errors', 'stocks')]
    selector.setCurrentIndex(0)
    bar.clear()
    assert len(calls) == 1
    future.set_result(65)
    bar.tick()
    assert refreshed and '65' in bar.feedback.text()
    future = Future()
    bar.clear()
    future.set_exception(RuntimeError('Redis unavailable'))
    bar.tick()
    assert '清空失败' in bar.feedback.text() and len(refreshed) == 1
    assert app
    bar.close()
