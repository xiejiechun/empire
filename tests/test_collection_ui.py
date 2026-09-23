import os
from concurrent.futures import Future
from copy import deepcopy
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

from empire.plugins.ui.collection import CollectionPage  # noqa: E402


class Runtime:
    def __init__(self):
        self.calls = []
        self.pending = None

    def invoke(self, *args):
        self.calls.append(args)
        if self.pending is not None:
            return self.pending
        future = Future()
        future.set_result("设置已保存")
        return future


def snapshot():
    return {"jobs": [{"id": "stocks", "name": "股票列表", "description": "股票",
        "policy": {"enabled": True, "mode": "manual", "interval_minutes": 1440,
                   "daily_time": "18:00", "request_retries": 2}, "active": None,
        "next_due": None, "last_status": "idle", "rate_group": "sina", "progress": {}}],
        "sites": [{"name": "sina", "domains": ["sina.com.cn"], "min_interval_ms": 2000,
                   "max_concurrency": 1}], "history": [], "error": ""}


@pytest.fixture
def page_factory():
    app = QApplication.instance() or QApplication([])
    pages = []

    def create(section="tasks"):
        page = CollectionPage(SimpleNamespace(runtime=Runtime(), cfg={}), section=section)
        page.timer.stop()
        page.data = snapshot()
        page.render()
        pages.append(page)
        return page

    yield create
    for page in pages:
        page.deleteLater()
    app.processEvents()


def test_form_edits_survive_status_refresh_and_save_selected_policy():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    page = CollectionPage(SimpleNamespace(runtime=runtime, cfg={}))
    page.timer.stop()
    page.data = snapshot()
    try:
        page.render()
        page.mode.setCurrentIndex(page.mode.findData("interval"))
        page.interval.setValue(30)
        page.render()
        assert page.interval.value() == 30
        assert page.mode.currentData() == "interval"
        page.save_job()
        assert runtime.calls[-1][0:3] == ("collection.control", "configure", "stocks")
        assert runtime.calls[-1][3]["interval_minutes"] == 30
        page.tick()
        assert page.feedback.text() == "设置已保存"
        page.data["jobs"][0]["active"] = {"run_id": "running"}
        page.tick()
        assert all(not button.isEnabled() for button in page.run_buttons)
    finally:
        page.deleteLater()
        app.processEvents()


@pytest.mark.parametrize(("section", "title", "index"), [
    ("tasks", "采集任务", 0), ("sites", "网站频控", 1), ("history", "运行记录", 2),
])
def test_sections_are_independent_pages_without_duplicate_tabs(page_factory, section, title, index):
    page = page_factory(section)
    assert page.title.text() == title
    assert page.tabs.currentIndex() == index
    assert len(page.findChildren(QTabWidget)) == 1
    assert page.history_tabs.count() == 3
    if section != "history":
        assert not page.history_tabs.isVisible()
    else:
        assert "采集 100 条 · 归档 100 条 · 错误 300 条" in page.summary.text()


def test_only_relevant_schedule_fields_show_and_drafts_survive_task_switch(page_factory):
    page = page_factory()
    assert page.interval.isHidden() and page.daily.isHidden()
    page.mode.setCurrentIndex(page.mode.findData("interval"))
    page.interval.setValue(30)
    assert not page.interval.isHidden() and page.daily.isHidden()
    assert "未保存" in page.task_feedback.text()
    second = deepcopy(page.data["jobs"][0])
    second.update(id="news", name="财经新闻")
    page.data["jobs"].append(second)
    page.render()
    page.jobs.selectRow(1)
    page.mode.setCurrentIndex(page.mode.findData("daily"))
    assert page.interval.isHidden() and not page.daily.isHidden()
    page.jobs.selectRow(0)
    assert page.interval.value() == 30
    assert page.mode.currentData() == "interval"
    assert page.save_button.isEnabled()
    page.reset_job()
    assert page.mode.currentData() == "manual"
    assert not page.save_button.isEnabled()


def test_save_discards_old_snapshot_and_preserves_edits_made_during_save(page_factory):
    page = page_factory()
    page.mode.setCurrentIndex(page.mode.findData("interval"))
    page.interval.setValue(30)
    page.shell.runtime.pending = Future()
    page.save_job()
    stale = Future()
    stale.set_result(snapshot())
    page.query = stale
    page.interval.setValue(45)
    page.shell.runtime.pending.set_result("设置已保存")
    page.tick()
    assert page.query is None
    assert page.interval.value() == 45
    assert page.job_baselines["stocks"]["interval_minutes"] == 30
    assert page.job_drafts["stocks"]["interval_minutes"] == 45
    assert "之后的修改尚未保存" in page.task_feedback.text()
    page.render()
    assert page.interval.value() == 45


def test_failed_save_keeps_draft_and_reenables_save(page_factory):
    page = page_factory()
    page.retries.setValue(4)
    page.shell.runtime.pending = Future()
    page.save_job()
    page.shell.runtime.pending.set_exception(RuntimeError("连接暂时中断"))
    page.tick()
    page.render()
    assert page.retries.value() == 4
    assert page.save_button.isEnabled()
    assert "连接暂时中断" in page.task_feedback.text()


def test_site_edits_and_save_feedback_are_independent_from_task_settings(page_factory):
    page = page_factory("sites")
    page.retries.setValue(4)
    page.site_interval.setValue(3100)
    page.render()
    assert page.site_interval.value() == 3100
    assert "及其子域名" in page.site_scope.text()
    assert "股票列表" in page.site_scope.text()
    page.save_site()
    assert page.shell.runtime.calls[-1] == ("collection.control", "configure_site", "sina", 3100)
    page.tick()
    page.render()
    assert page.site_feedback.text() == "设置已保存"
    assert "未保存" in page.task_feedback.text()
    assert not page.site_save.isEnabled()
    assert page.save_button.isEnabled()


def test_history_filters_preserve_full_error_and_reading_selection(page_factory):
    page = page_factory("history")
    error = "请求失败：" + "详细原因\n" * 100
    page.data["history"] = [
        {"run_id": "success", "task_id": "stocks", "started_at": 1, "finished_at": 92,
         "status": "complete", "error": "", "result": {"collected": 5566}, "origin": "schedule"},
        {"run_id": "failed", "task_id": "stocks", "started_at": 10, "finished_at": 75,
         "status": "error", "error": error, "result": {}, "origin": "manual"},
    ]
    page.render()
    assert page.history.item(0, 2).text() == "1 分 31 秒"
    assert page.history.item(0, 4).text() == "5,566"
    page.history_filter.setCurrentIndex(page.history_filter.findData("error"))
    assert page.history.rowCount() == 1
    assert page.history_records[0]["run_id"] == "failed"
    assert error in page.history_detail.toPlainText()
    cursor = page.history_detail.textCursor()
    cursor.setPosition(5)
    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 5)
    page.history_detail.setTextCursor(cursor)
    before = page.history_detail.textCursor().selectedText()
    page.render()
    assert page.history_detail.textCursor().selectedText() == before
    page.history_filter.setCurrentIndex(page.history_filter.findData("paused"))
    assert page.history.rowCount() == 0
    assert page.history_detail.toPlainText() == ""
    assert not page.history_empty.isHidden()


def test_shutdown_stops_collection_polling(page_factory):
    page = page_factory()
    page.shell.shutting_down = True
    page.tick()
    assert page.shell.runtime.calls == []
    assert not page.timer.isActive()
