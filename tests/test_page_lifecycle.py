import os
import threading
import weakref
from concurrent.futures import Future

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QVBoxLayout, QWidget  # noqa: E402

from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution  # noqa: E402
from empire.desktop.window import MainWindow  # noqa: E402
from empire.plugins.ui.queries import QueryScope  # noqa: E402


class Runtime:
    def __init__(self):
        self.closed = threading.Event()
        self.contributions = []
        self.reads = []

    def snapshot(self):
        return {"plugins": []}

    def page_contributions(self):
        return self.contributions

    def invoke(self, *args):
        future = Future()
        self.reads.append(future)
        return future

    def command(self, *args):
        future = Future()
        future.set_result(None)
        return future


class ReadPage(QWidget):
    instances = []

    def __init__(self, shell, page_id):
        super().__init__()
        self.page_id = page_id
        self.query_scope = QueryScope(self)
        self.editor = QLineEdit()
        layout = QVBoxLayout(self)
        layout.addWidget(self.editor)
        self.timer = QTimer(self)
        self.timer.setInterval(10000)
        self.timer.start()
        self.read = self.query_scope.invoke("read", shell.runtime, "test", "read")
        self.instances.append(weakref.ref(self))

    def save_ui_state(self):
        return {"text": self.editor.text()}

    def restore_ui_state(self, state):
        self.editor.setText(state["text"])


def drain_deletes(app):
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_page_cache_policy_is_explicit_and_editors_default_to_persistent():
    page = PageContribution("editor", "编辑器", lambda _: QWidget())
    assert page.cache_policy == "persistent"
    with pytest.raises(ValueError, match="cache policy"):
        PageContribution("bad", "错误", lambda _: QWidget(), cache_policy="unbounded")
    with pytest.raises(ValueError, match="too long"):
        NavigationContext(task_id="x" * 101)
    with pytest.raises(ValueError, match="page ID"):
        NavigationTarget("")


def test_100_read_pages_use_bounded_lru_stop_hidden_work_and_restore_state():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    runtime.contributions = [
        PageContribution(f"read-{index}", f"读取页 {index}",
                         lambda shell, ident=f"read-{index}": ReadPage(shell, ident),
                         "数据浏览", index, cache_policy="lru")
        for index in range(100)
    ]
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        first = window.page_widgets["read-0"]
        first_reference = weakref.ref(first)
        first.editor.setText("保留筛选状态")
        first_read = first.read
        del first
        for index in range(1, 100):
            assert window.navigate(f"read-{index}")
            assert len(window.page_registry.lru.used) <= 8
            assert len(window.page_widgets) <= 8
            assert sum(page.timer.isActive() for page in window.page_widgets.values()) == 1
        drain_deletes(app)
        assert first_read.cancelled()
        assert "read-0" not in window.page_widgets
        assert first_reference() is None
        assert sum(reference() is not None for reference in ReadPage.instances) <= 8
        assert window.navigate("read-0")
        assert window.page_widgets["read-0"].editor.text() == "保留筛选状态"
        assert sum(page.timer.isActive() for page in window.page_widgets.values()) == 1
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        drain_deletes(app)


def test_persistent_editor_and_untracked_write_survive_navigation():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    editor = QLineEdit()
    editor.action = Future()
    runtime.contributions = [
        PageContribution("editor", "编辑器", lambda _: editor, "工作台", 0, top_level=True),
        PageContribution("read", "读取页", lambda shell: ReadPage(shell, "read"),
                         "数据浏览", 0, cache_policy="lru"),
    ]
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        editor.setText("未保存草稿")
        assert window.navigate("read")
        assert not editor.action.cancelled()
        assert window.navigate("editor")
        assert window.page_widgets["editor"] is editor
        assert editor.text() == "未保存草稿"
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        drain_deletes(app)
