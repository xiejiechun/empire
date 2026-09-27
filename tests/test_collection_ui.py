import os
from concurrent.futures import Future
from copy import deepcopy
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

from empire.contracts.ui import NavigationContext  # noqa: E402
from empire.plugins.ui.collection import CollectionUiPlugin  # noqa: E402
from empire.plugins.ui.collection_views.tasks import TasksPage  # noqa: E402


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
        "policy": {"enabled": True, "mode": "manual", "interval_seconds": 86400,
                   "daily_time": "18:00", "request_retries": 2}, "active": None,
        "next_due": None, "last_status": "idle", "rate_group": "sina", "progress": {}}],
        "sites": [{"name": "sina", "domains": ["sina.com.cn"], "min_interval_ms": 2000,
                   "max_concurrency": 1}], "history": [], "error": ""}


def test_primary_actions_are_outside_editor_scroll_areas(page_factory):
    from PySide6.QtWidgets import QScrollArea

    def inside_scroll(widget):
        parent = widget.parentWidget()
        while parent is not None:
            if isinstance(parent, QScrollArea):
                return True
            parent = parent.parentWidget()
        return False

    tasks = page_factory()
    sites = page_factory("sites")
    for button in (tasks.run_button, tasks.pause_button, tasks.save_button,
                   sites.site_save, sites.site_reset):
        assert not inside_scroll(button)
    tasks.interval.setValue(123)
    for width, height in ((880, 560), (1320, 860), (680, 560), (880, 560)):
        tasks.resize(width, height)
        tasks.show()
        QApplication.processEvents()
        tasks.task_inspector.setCurrentIndex(1)
        scroll = tasks.task_inspector.currentWidget()
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        assert tasks.run_button.isVisible()
        assert tasks.pause_button.isVisible()
        assert tasks.interval.value() == 123
    tasks.resize(680, 560)
    QApplication.processEvents()
    assert tasks.task_split.orientation() == Qt.Orientation.Vertical
    assert tasks.task_filters.getItemPosition(tasks.task_filters.indexOf(tasks.task_search)) == (0, 0, 1, 3)
    assert tasks.jobs.isColumnHidden(1)
    assert not tasks.jobs.isColumnHidden(3)
    tasks.resize(1200, 700)
    QApplication.processEvents()
    assert tasks.task_split.orientation() == Qt.Orientation.Horizontal
    assert tasks.task_filters.getItemPosition(tasks.task_filters.indexOf(tasks.task_status))[0] == 0
    assert not tasks.jobs.isColumnHidden(1)


@pytest.fixture
def page_factory():
    app = QApplication.instance() or QApplication([])
    pages = []

    def create(section="tasks"):
        ident = "collection" if section == "tasks" else section
        contribution = next(p for p in CollectionUiPlugin().create_pages() if p.id == ident)
        page = contribution.factory(SimpleNamespace(runtime=Runtime(), cfg={}))
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
    page = TasksPage(SimpleNamespace(runtime=runtime, cfg={}))
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
        assert runtime.calls[-1][3]["interval_seconds"] == 30
        page.tick()
        assert page.feedback.text() == "设置已保存"
        page.data["jobs"][0]["active"] = {"run_id": "running"}
        page.tick()
        assert all(not button.isEnabled() for button in page.run_buttons)
    finally:
        page.deleteLater()
        app.processEvents()


@pytest.mark.parametrize(("section", "title", "index"), [
    ("tasks", "采集任务", 0), ("sites", "站点访问规则", 1), ("history", "运行记录", 2),
])
def test_sections_are_independent_pages_without_duplicate_tabs(page_factory, section, title, index):
    page = page_factory(section)
    assert page.title.text() == title
    assert page.section == section
    assert len(page.findChildren(QTabWidget)) == (1 if section in ("history", "tasks") else 0)
    if section == "tasks":
        assert [page.task_inspector.tabText(i) for i in range(page.task_inspector.count())] == ["运行详情", "任务配置"]
    if section != "history":
        assert not hasattr(page, "history_tabs")
    else:
        assert page.history_tabs.count() == 3
        assert "采集 100 条 · 归档 100 条 · 错误 300 条" in page.summary.text()
    assert hasattr(page, "jobs") == (section == "tasks")
    assert hasattr(page, "site_interval") == (section == "sites")


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
    assert page.job_baselines["stocks"]["interval_seconds"] == 30
    assert page.job_drafts["stocks"]["interval_seconds"] == 45
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
    task_page = page_factory("tasks")
    task_page.retries.setValue(4)
    page.site_interval.setValue(3100)
    page.render()
    assert page.site_interval.value() == 3100
    assert "及其子域名" in page.site_scope.text()
    assert "股票列表" in page.site_scope.text()
    page.save_site()
    assert page.shell.runtime.calls[-1] == ("collection.control", "configure_site", "sina",
        {"min_interval_ms": 3100, "proxy_interval_ms": 2000,
         "total_interval_ms": 500, "max_concurrency": 1, "scaling_mode": "fixed", "max_rps": 0})
    page.tick()
    page.render()
    assert page.site_feedback.text() == "设置已保存"
    assert "未保存" in task_page.task_feedback.text()
    assert not page.site_save.isEnabled()
    assert task_page.save_button.isEnabled()


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


def test_proxy_choices_survive_refresh_and_save_with_task_policy(page_factory):
    page = page_factory()
    assert page.route_mode.currentData() == "direct"
    page.route_mode.setCurrentIndex(page.route_mode.findData("proxy_only"))
    page.render()
    assert page.route_mode.currentData() == "proxy_only"
    page.save_job()
    policy = page.shell.runtime.calls[-1][-1]
    assert policy["use_proxy"] is True and policy["proxy_fallback"] is False
    page.tick()
    assert not page.save_button.isEnabled()


def test_context_focus_preserves_filters_page_and_other_task_drafts(page_factory):
    page = page_factory()
    page.task_search.setText("原筛选")
    page.offset = 50
    page.mode.setCurrentIndex(page.mode.findData("interval"))
    page.interval.setValue(37)
    assert "stocks" in page.job_drafts
    page.apply_navigation_context(NavigationContext(task_id="sina-news"))
    assert page.task_search.text() == "原筛选"
    assert page.offset == 50
    assert page.focus_task_id == "sina-news"
    assert page._query_args()[-2:] == ("", "sina-news")
    focused = snapshot()
    focused["jobs"][0].update(id="sina-news", name="财经快讯")
    focused.update(total=1, offset=0, limit=25, focused_task_id="sina-news")
    page.data = focused
    page.render()
    assert page.loaded_id == "sina-news"
    assert "stocks" in page.job_drafts
    assert not page.clear_focus_button.isHidden()
    page.clear_navigation_focus()
    assert page.focus_task_id is None
    assert page.offset == 50
    assert page.task_search.text() == "原筛选"
    assert "stocks" in page.job_drafts


def test_automatic_capacity_draft_survives_refresh_and_preserves_custom_ceiling(page_factory):
    page = page_factory("sites")
    page.rate_fields.mode.setCurrentIndex(page.rate_fields.mode.findData("auto"))
    page.rate_fields.inputs["max_concurrency"].setValue(32)
    page.rate_fields.inputs["max_rps"].setValue(12)
    page.render()
    assert page.rate_fields.values()["max_concurrency"] == 32
    assert page.rate_fields.values()["max_rps"] == 12
    page.save_site()
    assert page.shell.runtime.calls[-1][-1]["scaling_mode"] == "auto"
    page.tick()
    page.render()
    assert page.rate_fields.values()["max_concurrency"] == 32
    assert not page.site_save.isEnabled()
