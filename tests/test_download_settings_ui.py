"""Resource settings keep durable values, active values and edit drafts distinct."""
import os
import threading
from concurrent.futures import Future
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QFontDatabase, QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from empire.contracts.download_settings import (  # noqa: E402
    DEVICE_TIERS,
    FIELDS,
    recommended_settings,
)
from empire.desktop.interaction import install_input_rules  # noqa: E402
from empire.desktop.theme import STYLE  # noqa: E402
from empire.desktop.window import MainWindow  # noqa: E402
from empire.plugins.ui.downloads import DownloadSettingsPage, DownloadSettingsUiPlugin  # noqa: E402


def defaults():
    return {field.key: field.default for field in FIELDS}


def snapshot(saved=None, active=None):
    saved = saved if saved is not None else defaults()
    active = active if active is not None else defaults()
    return {"saved": deepcopy(saved), "active": deepcopy(active), "pending_restart": saved != active}


class Runtime:
    def __init__(self):
        self.calls = []
        self.pending = None
        self.data = snapshot()

    def invoke(self, *args):
        self.calls.append(args)
        if self.pending is not None:
            return self.pending
        future = Future()
        if args[1] == "save":
            self.data = snapshot(args[2])
        future.set_result(deepcopy(self.data))
        return future


@pytest.fixture
def page():
    app = QApplication.instance() or QApplication([])
    font = Path("C:/Windows/Fonts/msyh.ttc")
    if not QFontDatabase.families() and font.exists():
        QFontDatabase.addApplicationFont(str(font))
    widget = DownloadSettingsPage(SimpleNamespace(runtime=Runtime(), cfg={}))
    widget.timer.stop()
    widget.apply_snapshot(snapshot())
    yield widget
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_refresh_preserves_draft_and_updates_saved_and_active_separately(page):
    page.fields.inputs["buffer_budget_bytes"].setValue(128)
    changed = defaults() | {"buffer_budget_bytes": 96 * 1024 * 1024}
    page.apply_snapshot(snapshot(changed))
    assert page.fields.inputs["buffer_budget_bytes"].value() == 128
    assert page.saved["buffer_budget_bytes"] == 96 * 1024 * 1024
    assert page.active["buffer_budget_bytes"] == 512 * 1024 * 1024
    assert "当前生效：512 MiB" in page.fields.states["buffer_budget_bytes"].text()
    assert "已保存：96 MiB" in page.fields.states["buffer_budget_bytes"].text()
    assert "重启软件后生效" in page.summary.text()
    assert page.save_button.isEnabled()
    page.reset()
    assert page.fields.inputs["buffer_budget_bytes"].value() == 96
    assert not page.save_button.isEnabled()


def test_save_uses_bytes_and_does_not_change_active_limits(page):
    page.fields.inputs["buffer_budget_bytes"].setValue(128)
    page.fields.inputs["calendar_response_bytes"].setValue(1024)
    assert page.save_button.isEnabled()
    page.save()
    sent = page.shell.runtime.calls[-1]
    assert sent[:2] == ("download.settings", "save")
    assert sent[2]["buffer_budget_bytes"] == 128 * 1024 * 1024
    assert sent[2]["calendar_response_bytes"] == 1024 * 1024
    page.tick()
    assert page.saved == sent[2]
    assert page.active == defaults()
    assert page.pending_restart
    assert "重启软件后生效" in page.feedback.text()
    assert not page.dirty and not page.save_button.isEnabled()


def test_edits_during_save_survive_acknowledgement_and_stale_snapshot(page):
    page.fields.inputs["buffer_budget_bytes"].setValue(128)
    pending = page.shell.runtime.pending = Future()
    page.save()
    submitted = deepcopy(page.submitted)
    stale = page.query_scope.track(Future())
    stale.set_result(snapshot())
    page.query = stale
    page.fields.inputs["buffer_budget_bytes"].setValue(160)
    pending.set_result(snapshot(submitted))
    page.tick()
    assert page.query is None
    assert page.saved["buffer_budget_bytes"] == 128 * 1024 * 1024
    assert page.fields.inputs["buffer_budget_bytes"].value() == 160
    assert page.save_button.isEnabled()
    assert "之后的修改尚未保存" in page.feedback.text()
    page.apply_snapshot(snapshot(submitted))
    assert page.fields.inputs["buffer_budget_bytes"].value() == 160


def test_failed_save_keeps_draft_and_retry_enabled(page):
    page.fields.inputs["buffer_budget_bytes"].setValue(128)
    pending = page.shell.runtime.pending = Future()
    page.save()
    pending.set_exception(RuntimeError("数据库暂时不可用"))
    page.tick()
    assert page.fields.inputs["buffer_budget_bytes"].value() == 128
    assert page.saved == defaults()
    assert page.save_button.isEnabled()
    assert "数据库暂时不可用" in page.feedback.text()


def test_defaults_only_change_draft_and_reset_restores_saved_values(page):
    changed = defaults() | {"buffer_budget_bytes": 128 * 1024 * 1024}
    page.apply_snapshot(snapshot(changed, changed))
    page.restore_defaults()
    assert page.fields.values() == defaults()
    assert page.saved == changed
    assert not page.shell.runtime.calls
    assert "草稿" in page.feedback.text()
    page.reset()
    assert page.fields.values() == changed
    assert not page.dirty


def test_invalid_cross_field_budget_blocks_save_until_corrected(page):
    page.fields.inputs["buffer_budget_bytes"].setValue(16)
    page.fields.inputs["news_response_bytes"].setValue(16 * 1024)
    assert page.validation.text()
    assert not page.save_button.isEnabled()
    page.save()
    assert not page.shell.runtime.calls
    page.fields.inputs["buffer_budget_bytes"].setValue(64)
    assert not page.validation.text()
    assert page.save_button.isEnabled()


def test_http_service_stopped_still_allows_saved_configuration(page):
    page.apply_snapshot({"saved": defaults(), "active": None, "pending_restart": False})
    assert "HTTP 服务未启动" in page.summary.text()
    assert "HTTP 服务未启动" in page.fields.states["file_response_bytes"].text()
    page.fields.inputs["file_response_bytes"].setValue(300)
    assert page.save_button.isEnabled()


def test_failed_refresh_marks_old_values_and_preserves_draft_until_recovery(page):
    page.fields.inputs["buffer_budget_bytes"].setValue(128)
    page.query = page.query_scope.track(Future())
    page.query.set_exception(RuntimeError("连接中断"))
    page.tick()
    assert page.fields.inputs["buffer_budget_bytes"].value() == 128
    assert "上次读取的生效值" in page.fields.states["buffer_budget_bytes"].text()
    assert "上次读取的已保存值" in page.fields.states["buffer_budget_bytes"].text()
    assert "未保存草稿已保留" in page.summary.text()
    page.apply_snapshot(snapshot())
    assert "当前生效：512 MiB" in page.fields.states["buffer_budget_bytes"].text()
    assert page.fields.inputs["buffer_budget_bytes"].value() == 128
    assert page.save_button.isEnabled()


def test_destroying_page_cancels_reads_but_not_pending_write():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    widget = DownloadSettingsPage(SimpleNamespace(runtime=runtime, cfg={}))
    widget.timer.stop()
    widget.apply_snapshot(snapshot())
    read = widget.query_scope.track(Future())
    widget.query = read
    widget.fields.inputs["buffer_budget_bytes"].setValue(128)
    write = runtime.pending = Future()
    widget.save()
    widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert read.cancelled()
    assert not write.cancelled()
    write.set_result(snapshot(runtime.calls[-1][2]))
    assert write.done()
    app.processEvents()


def test_download_ui_plugin_contributes_page_only_when_started():
    plugin = DownloadSettingsUiPlugin()
    assert plugin.pages == ()
    contribution, = plugin.create_pages()
    assert (contribution.id, contribution.title, contribution.group) == ("downloads", "下载资源", "采集管理")
    assert contribution.factory is DownloadSettingsPage


@pytest.mark.parametrize("width", [1040, 520])
def test_save_bar_remains_visible_with_scrollable_content(page, width):
    app = QApplication.instance()
    page.setStyleSheet(STYLE)
    page.resize(width, 600)
    page.show()
    app.processEvents()
    assert page.width() == width
    assert page.editor.verticalScrollBar().maximum() > 0
    assert page.editor.horizontalScrollBar().maximum() == 0
    assert page.save_bar.y() >= page.editor.geometry().bottom()
    assert page.save_bar.geometry().bottom() <= page.height()
    for button in (page.save_button, page.reset_button, page.defaults_button):
        assert page.save_bar.rect().contains(button.geometry())
    page.editor.verticalScrollBar().setValue(page.editor.verticalScrollBar().maximum())
    app.processEvents()
    assert page.save_bar.isVisible()
    page.hide()


def test_global_scroll_safety_applies_to_download_inputs(page):
    app = QApplication.instance()
    install_input_rules(app)
    before = page.fields.values()
    for spin in page.fields.inputs.values():
        event = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(), QPoint(0, 120),
                            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                            Qt.ScrollPhase.ScrollUpdate, False)
        QApplication.sendEvent(spin, event)
        assert page.fields.values() == before


@pytest.mark.parametrize("device_count", DEVICE_TIERS)
def test_ten_capacity_tiers_fill_only_resource_draft_without_saving(page, device_count):
    count = page.fields.inputs["planned_exit_devices"]
    assert isinstance(count, QComboBox)
    assert not count.isEditable()
    assert [count.itemData(i) for i in range(count.count())] == list(DEVICE_TIERS)
    page.fields.inputs["file_response_bytes"].setValue(300)
    page.fields.inputs["news_response_bytes"].setValue(8192)
    count.setCurrentIndex(count.findData(device_count))
    original = page.fields.values()
    page.fields.recommendation.button.click()
    assert page.fields.values() == recommended_settings(device_count, original)
    assert page.saved == defaults() and page.active == defaults()
    assert page.shell.runtime.calls == []
    assert page.fields.values()["file_response_bytes"] == 300 * 1024 * 1024
    assert page.fields.values()["news_response_bytes"] == 8 * 1024 * 1024
    assert "尚未保存" in page.feedback.text()
    assert "不是实际并发" in page.fields.recommendation.preview.text()
    page.apply_snapshot(snapshot())
    assert page.fields.values() == recommended_settings(device_count, original)


def test_invalid_tier_and_oversized_custom_response_cannot_apply_recommendation(page):
    count = page.fields.inputs["planned_exit_devices"]
    count.setCurrentIndex(-1)
    invalid = page.fields.values()
    assert not page.save_button.isEnabled()
    assert not page.fields.recommendation.button.isEnabled()
    page.fields.recommendation.apply()
    assert page.fields.values() == invalid
    count.setCurrentIndex(count.findData(1000))
    page.fields.inputs["stock_response_bytes"].setValue(32 * 1024)
    oversized = page.fields.values()
    assert not page.fields.recommendation.button.isEnabled()
    assert "暂不能推荐" in page.fields.recommendation.preview.text()
    page.fields.recommendation.apply()
    assert page.fields.values() == oversized
    assert not page.shell.runtime.calls


def test_default_hundred_device_recommendation_is_already_saved(page):
    assert page.fields.inputs["planned_exit_devices"].currentData() == 100
    assert page.fields.inputs["max_parallel_downloads"].value() == 128
    assert page.fields.inputs["buffer_budget_bytes"].value() == 512
    page.fields.recommendation.button.click()
    assert not page.dirty and not page.save_button.isEnabled()
    assert "无须重复保存" in page.feedback.text()
    assert not page.shell.runtime.calls


def test_recommendation_after_save_submission_survives_acknowledgement(page):
    count = page.fields.inputs["planned_exit_devices"]
    count.setCurrentIndex(count.findData(200))
    page.fields.recommendation.button.click()
    pending = page.shell.runtime.pending = Future()
    page.save()
    submitted = deepcopy(page.submitted)
    count.setCurrentIndex(count.findData(1000))
    page.fields.recommendation.button.click()
    later = page.fields.values()
    pending.set_result(snapshot(submitted))
    page.tick()
    assert page.saved == submitted
    assert page.fields.values() == later
    assert page.dirty
    assert "之后的修改尚未保存" in page.feedback.text()


@pytest.mark.parametrize("width", [1320, 880])
def test_nested_shell_reflows_async_snapshot_without_label_overlap(page, width):
    class ShellRuntime(Runtime):
        def __init__(self):
            super().__init__()
            self.closed = threading.Event()

        def snapshot(self):
            return {"plugins": []}

        def page_contributions(self):
            return DownloadSettingsUiPlugin().create_pages()

    runtime = ShellRuntime()
    window = MainWindow(runtime, {})
    window.timer.stop()
    nested = window.page_widgets["downloads"]
    nested.timer.stop()
    window.resize(width, 700)
    window.show()
    try:
        QTest.qWait(30)
        # Initially a one-line placeholder; the real async reply requires layout propagation
        # through both scroll areas, not just a single QApplication.processEvents() call.
        nested.apply_snapshot(snapshot())
        QTest.qWait(150)
        for key, spin in nested.fields.inputs.items():
            state = nested.fields.states[key]
            assert state.y() > spin.geometry().bottom()
            assert state.height() >= state.heightForWidth(state.width())
            assert spin.parentWidget().rect().contains(state.geometry())
        assert nested.editor.horizontalScrollBar().maximum() == 0
        assert nested.save_bar.geometry().bottom() <= nested.height()
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
