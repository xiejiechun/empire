"""Status remains readable while a fair archive queue has unfinished work."""
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.mark.parametrize("width,height", [(880, 720), (1320, 900)])
def test_archive_scheduling_metrics_are_visible_without_overlapping_actions(width, height):
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    from empire.desktop.theme import STYLE
    from empire.plugins.ui.system import SystemStatusPage

    app = QApplication.instance() or QApplication([])
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    health = {"scan_more": True, "indexed_messages": 3000, "ready_projects": 3,
              "retry_projects": 1, "scan_messages": 500, "scan_bytes": 1024 * 1024,
              "work_units": 32, "staging_batches": 2}
    data = {"plugins": [{"id": "pipeline.archive", "name": "归档", "state": "DEGRADED",
                         "health": health, "error": "某个测试项目等待重试，消息已保留"},
                        {"id": "infra.mysql", "name": "数据库", "state": "RUNNING", "health": {
                            "lanes": {"read": {"active": 2, "waiting": 16, "capacity": 18, "rejected": 3},
                                      "control": {"active": 1, "waiting": 2, "capacity": 33}}}}]}
    shell = SimpleNamespace(runtime=SimpleNamespace(snapshot=lambda: data), cfg={},
                            command=lambda *args: None, navigate=lambda *args: None)
    page = SystemStatusPage(shell)
    page.setStyleSheet(STYLE)
    try:
        page.resize(width, height)
        page.show()
        app.processEvents()
        values = {page.metrics.item(i, 0).text(): page.metrics.item(i, 1).text()
                  for i in range(page.metrics.rowCount())}
        assert values["可调度 / 等待重试项目"] == "3 / 1"
        assert values["归档已索引消息"] == "3000"
        assert values["归档扫描待继续"] == "是，正在分轮处理"
        assert values["数据库浏览执行 / 等待"] == "2 / 16"
        assert values["数据库浏览容量 / 满队拒绝"] == "18 / 3"
        assert values["数据库归档与配置执行 / 等待"] == "1 / 2"
        assert page.values["archive"].text() == "运行异常"
        assert page.metrics.geometry().bottom() < page.issues.geometry().top()
        assert page.connections.geometry().bottom() <= page.height()
        target = Path(__file__).resolve().parents[1] / "artifacts" / f"archive-fairness-status-{width}.png"
        target.parent.mkdir(exist_ok=True)
        assert page.grab().save(str(target))
    finally:
        page.timer.stop()
        page.close()
        page.deleteLater()
        app.processEvents()
