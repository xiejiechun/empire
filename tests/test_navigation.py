import os
import threading
from concurrent.futures import Future

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from empire.contracts.ui import PageContribution  # noqa: E402
from empire.desktop.window import MainWindow  # noqa: E402


class Runtime:
    def __init__(self):
        self.closed = threading.Event()
        self.contributions = [
            PageContribution("plugins", "插件管理", lambda shell: QLineEdit(), "系统管理"),
            PageContribution("stocks", "股票列表", lambda shell: QLineEdit(), "数据中心"),
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


def test_navigation_groups_keep_page_state_and_recover_after_plugin_removal():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        assert window.current_page_id == "home"
        assert window.nav.item(0).text() == "工作台"
        assert not window.nav.item(0).flags() & Qt.ItemFlag.ItemIsSelectable
        assert window.navigate("stocks")
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
