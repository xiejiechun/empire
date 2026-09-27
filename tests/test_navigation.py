import os
import threading
from concurrent.futures import Future

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit, QWidget  # noqa: E402

from empire.contracts.ui import (  # noqa: E402
    NavigationContext,
    NavigationTarget,
    PageContribution,
)
from empire.desktop.window import MainWindow  # noqa: E402


class Runtime:
    def __init__(self):
        self.closed = threading.Event()
        self.contributions = [
            PageContribution("plugins", "插件管理", lambda shell: QLineEdit(), "系统设置"),
            PageContribution("stocks", "股票列表", lambda shell: QLineEdit(), "数据浏览"),
            PageContribution("home", "总览", lambda shell: QLineEdit(), "工作台"),
        ]

    def snapshot(self):
        return {"plugins": []}

    def page_contributions(self):
        return self.contributions

    def command(self, *args):
        result = Future()
        result.set_result(None)
        return result


def test_initial_window_fits_available_logical_screen():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        window.show()
        app.processEvents()
        available = window.screen().availableGeometry()
        assert window.width() <= available.width()
        assert window.height() <= available.height()
        assert window.minimumWidth() <= 640
        assert window.minimumHeight() <= 360
        window.resize(800, 560)
        app.processEvents()
        assert window.sidebar.width() == 148
        assert window.nav.isVisible()
        window.resize(1200, 700)
        app.processEvents()
        assert window.sidebar.width() == 184
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_navigation_groups_keep_page_state_and_recover_after_plugin_removal():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        assert window.current_page_id == "home"
        assert window.nav.item(0).text() == "工作台"
        assert window.nav.item(0).flags() & Qt.ItemFlag.ItemIsSelectable
        assert window.nav.count() == 3
        assert window.subnav.item(0).text() == "总览"
        assert window.navigate("stocks")
        assert window.nav.currentItem().text() == "数据浏览"
        assert window.subnav.currentItem().text() == "股票列表"
        assert window.breadcrumb.text() == "数据浏览  /  股票列表"
        stock_page = window.page_widgets["stocks"]
        stock_page.setText("未保存的查询")
        assert window.navigate("home")
        runtime.contributions.append(PageContribution("collection", "采集任务", lambda shell: QLineEdit(), "采集管理"))
        window.refresh()
        assert window.navigate("stocks")
        assert window.page_widgets["stocks"] is stock_page
        assert stock_page.text() == "未保存的查询"
        runtime.contributions = [p for p in runtime.contributions if p.id != "stocks"]
        window.refresh()
        assert window.current_page_id == "home"
        assert not window.navigate("stocks")
        runtime.contributions = []
        window.refresh()
        assert window.pages.currentIndex() == 0
        assert window.current_page_id is None
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_page_factory_failure_is_local_and_retryable():
    from PySide6.QtWidgets import QLabel, QPushButton

    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    attempts = 0

    def factory(shell):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("page factory unavailable")
        return QLineEdit("recovered")

    runtime.contributions = [PageContribution("home", "总览", factory, "工作台")]
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        assert attempts == 1
        failed = window.page_widgets["home"]
        assert any("暂时无法打开" in label.text() for label in failed.findChildren(QLabel))
        retry = next(button for button in failed.findChildren(QPushButton)
                     if button.text() == "重试打开页面")
        retry.click()
        app.processEvents()
        assert attempts == 2
        assert isinstance(window.page_widgets["home"], QLineEdit)
        assert window.page_widgets["home"].text() == "recovered"
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_management_navigation_uses_contribution_context_without_shell_business_rules():
    class TargetPage(QWidget):
        def __init__(self):
            super().__init__()
            self.contexts = []

        def apply_navigation_context(self, context):
            self.contexts.append(context)

    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    target = TargetPage()
    context = NavigationContext(task_id="plugin-owned-task")
    runtime.contributions = [
        PageContribution("source", "业务数据", lambda _: QLineEdit(), "数据浏览",
                         management=NavigationTarget("manager", context)),
        PageContribution("manager", "任务管理", lambda _: target, "采集管理"),
    ]
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        assert window.navigate_management("source")
        assert window.current_page_id == "manager"
        assert target.contexts == [context]
        assert not window.navigate_management("manager")
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_navigation_context_is_delivered_once_on_same_page_and_cleared_when_unsupported():
    class TargetPage(QWidget):
        def __init__(self):
            super().__init__()
            self.contexts = []

        def apply_navigation_context(self, context):
            self.contexts.append(context)

    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    target = TargetPage()
    runtime.contributions = [
        PageContribution("manager", "任务管理", lambda _: target, "采集管理"),
        PageContribution("plain", "普通页面", lambda _: QLineEdit(), "系统设置"),
    ]
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        first = NavigationContext(task_id="task-a")
        second = NavigationContext(task_id="task-b")
        assert window.navigate("manager", first)
        assert window.navigate("manager", second)
        assert target.contexts == [first, second]
        assert "manager" not in window.pending_navigation_contexts
        assert window.navigate("plain", first)
        assert "plain" not in window.pending_navigation_contexts
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_navigation_context_survives_page_factory_failure_until_retry():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    attempts = 0
    contexts = []

    class TargetPage(QWidget):
        def apply_navigation_context(self, context):
            contexts.append(context)

    def factory(_):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary failure")
        return TargetPage()

    runtime.contributions = [PageContribution("manager", "任务管理", factory, "采集管理")]
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        context = NavigationContext(task_id="task-a")
        assert window.navigate("manager", context)
        assert contexts == []
        assert window.pending_navigation_contexts["manager"] == context
        window._retry_page("manager")
        app.processEvents()
        assert attempts == 2
        assert contexts == [context]
        assert "manager" not in window.pending_navigation_contexts
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        app.processEvents()


async def test_workspace_direct_help_and_collection_grouping():
    from dataclasses import replace

    from empire.bootstrap import build_manager

    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    manager = build_manager({"redis": {}, "mysql": {}, "archive": {}, "ingest": {}, "rate_groups": {}})
    pages = []
    for ident, entry in manager.entries.items():
        if ident.startswith("ui."):
            provided = await entry.plugin.start(None)
            pages.extend(next(iter(provided.values())))
    management = {page.id: page.management for page in pages if page.management is not None}
    assert {key: value.context.task_id for key, value in management.items()} == {
        "stocks": "sina-stocks", "news": "sina-news", "calendar": "cninfo-calendar"
    }
    assert all(value.page_id == "collection" for value in management.values())
    runtime.contributions = [replace(p, factory=lambda shell: QLineEdit()) for p in pages]
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        assert [window.nav.item(i).text() for i in range(window.nav.count())] == [
            "工作台", "数据浏览", "采集管理", "系统设置", "说明文档"]
        assert window.current_page_id == "home"
        assert window.subnav.isHidden()
        window.nav.setCurrentRow(4)
        assert window.current_page_id == "help"
        assert window.breadcrumb.text() == "说明文档"
        assert window.subnav.isHidden()
        assert window.navigate("sites")
        assert window.nav.currentItem().text() == "采集管理"
        assert not window.subnav.isHidden()
        assert [window.subnav.item(i).text() for i in range(window.subnav.count())] == [
            "采集任务", "运行记录", "站点访问规则", "采集出口", "下载资源"]
        window.nav.setCurrentRow(4)
        window.nav.setCurrentRow(2)
        assert window.current_page_id == "sites"
        assert window.navigate("system")
        assert [window.subnav.item(i).text() for i in range(window.subnav.count())] == [
            "运行状态", "插件管理"]
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        app.processEvents()
