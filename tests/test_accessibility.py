import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QAccessible, QKeySequence, QShortcut  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from test_collection_ui import Runtime as CollectionRuntime  # noqa: E402
from test_collection_ui import snapshot
from test_navigation import Runtime  # noqa: E402

from empire.desktop import theme  # noqa: E402
from empire.desktop.theme import STYLE  # noqa: E402
from empire.plugins.ui.catalog import DataCatalogPage  # noqa: E402
from empire.plugins.ui.collection_views.tasks import TasksPage  # noqa: E402
from empire.plugins.ui.help import StorageHelpPage  # noqa: E402


def test_search_filters_and_navigation_have_stable_accessible_names():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    catalog = DataCatalogPage(SimpleNamespace(runtime=runtime, navigate=lambda _: None))
    tasks = TasksPage(SimpleNamespace(runtime=CollectionRuntime(), cfg={}))
    tasks.timer.stop()
    tasks.data = snapshot()
    tasks.render()
    help_page = StorageHelpPage(None)
    try:
        controls = (
            catalog.search, catalog.category, catalog.source, catalog.table,
            tasks.task_search, tasks.task_category, tasks.task_source,
            tasks.task_status, tasks.jobs, tasks.mode, tasks.interval,
            tasks.daily, tasks.retries, tasks.route_mode,
            help_page.search, help_page.tabs, help_page.index, help_page.browser,
        )
        assert all(control.accessibleName().strip() for control in controls)
        assert all(QAccessible.queryAccessibleInterface(control).text(QAccessible.Text.Name).strip()
                   for control in controls)

        tasks.interval.setValue(123)
        save = next(shortcut for shortcut in tasks.findChildren(QShortcut)
                    if shortcut.key() == QKeySequence(QKeySequence.StandardKey.Save))
        save.activated.emit()
        assert tasks.shell.runtime.calls[-1][0:3] == ("collection.control", "configure", "stocks")

        help_page.show()
        shortcut = help_page._accessibility_shortcuts[0]
        assert shortcut.key() == QKeySequence(QKeySequence.StandardKey.Find)
        shortcut.activated.emit()
        app.processEvents()
        assert help_page.search.hasFocus()
    finally:
        catalog.deleteLater()
        tasks.deleteLater()
        help_page.deleteLater()
        app.processEvents()


def test_theme_keeps_visible_keyboard_focus_for_lists_tables_and_primary_actions():
    assert "QListWidget::item:focus" in STYLE
    assert "QTableWidget::item:focus" in STYLE
    assert "QListWidget:focus, QTableWidget:focus, QTabBar:focus" not in STYLE
    assert "QTabBar::tab:focus" in STYLE
    assert "QPushButton#primary:focus" in STYLE


def test_high_contrast_uses_native_windows_palette(monkeypatch):
    monkeypatch.setattr(theme, "windows_high_contrast", lambda: True)
    assert theme.desktop_style() == ""
    monkeypatch.setattr(theme, "windows_high_contrast", lambda: False)
    assert theme.desktop_style() == STYLE


def test_interactive_boundaries_meet_three_to_one_contrast_target():
    def luminance(color):
        channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [channel / 12.92 if channel <= .04045 else ((channel + .055) / 1.055) ** 2.4
                  for channel in channels]
        return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2]

    def ratio(first, second):
        light, dark = sorted((luminance(first), luminance(second)), reverse=True)
        return (light + .05) / (dark + .05)

    assert ratio("#858f9f", "#ffffff") >= 3  # Input boundary.
    assert ratio("#747f90", "#ffffff") >= 3  # Unchecked checkbox.
    assert ratio("#7d899a", "#fafbfc") >= 3  # Scroll thumb against track.
    assert ratio("#2459b8", "#ffffff") >= 4.5  # Focus indicator.
