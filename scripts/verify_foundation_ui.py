"""Render deterministic desktop layouts without databases or production mutations."""
import os
import sys
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from test_collection_ui import snapshot  # noqa: E402

from empire.contracts.ui import PageContribution  # noqa: E402
from empire.desktop.window import MainWindow  # noqa: E402
from empire.plugins.ui.collection_views.sites import SitesPage  # noqa: E402
from empire.plugins.ui.collection_views.tasks import TasksPage  # noqa: E402
from empire.plugins.ui.proxies import ProxyPage  # noqa: E402


class Runtime:
    closed = SimpleNamespace(is_set=lambda: False)

    def snapshot(self):
        return {"plugins": []}

    def page_contributions(self):
        return [PageContribution(key, title, factory, "采集管理", order)
                for order, (key, title, factory) in enumerate([
                    ("collection", "采集任务", TasksPage), ("sites", "站点访问规则", SitesPage),
                    ("proxies", "采集出口", ProxyPage)])]

    def invoke(self, *args):
        return Future()


app = QApplication.instance() or QApplication([])
for font in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
    QFontDatabase.addApplicationFont(str(Path(os.environ["WINDIR"]) / "Fonts" / font))
window = MainWindow(Runtime(), {})
window.timer.stop()
out = Path(__file__).resolve().parents[1] / "build" / "foundation-ui"
out.mkdir(parents=True, exist_ok=True)
scale = os.environ.get("QT_SCALE_FACTOR", "1")
for width, height in [(1320, 860), (880, 560)]:
    window.resize(width, height)
    window.show()
    for page_id in ("collection", "sites", "proxies"):
        window.navigate(page_id)
        page = window.page_widgets[page_id]
        page.timer.stop()
        if page_id != "proxies":
            page.data = snapshot()
            page.data.update(total=1, offset=0)
            page.render()
        else:
            result = Future()
            result.set_result({"error": "", "online": 50, "online_egresses": 50,
                "waiting": 0, "invalid": 0, "devices": [
                    {"code": f"node{i:03}", "proxy_address": f"127.0.0.1:{31000+i}",
                     "exit_ip": f"192.0.2.{i+1}", "protocol": "SOCKS5", "cooldown_seconds": 0,
                     "busy": 0, "requests": i} for i in range(50)]})
            page.queries["pool"] = result
            page.tick()
        app.processEvents()
        if page_id == "collection":
            page.task_inspector.setCurrentIndex(1)
            page.interval.setValue(42)
            app.processEvents()
            window.page_containers[page_id].ensureWidgetVisible(page.save_button)
            app.processEvents()
            point = page.save_button.mapTo(window, QPoint(0, 0))
            assert point.y() >= 0 and point.y() + page.save_button.height() <= window.height()
            assert point.x() >= 0 and point.x() + page.save_button.width() <= window.width()
        window.grab().save(str(out / f"{page_id}-{width}-{scale}.png"))
        print(f"PASS scale={scale} size={width}x{height} page={page_id} actual={window.width()}x{window.height()}")
window.can_close = True
window.close()
