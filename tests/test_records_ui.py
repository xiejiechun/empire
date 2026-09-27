import os
from concurrent.futures import Future
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel  # noqa: E402
from PySide6.QtGui import QFontDatabase, QTextCursor  # noqa: E402
from PySide6.QtWidgets import QApplication, QHeaderView  # noqa: E402

from empire.plugins.ui.record_detail import record_time  # noqa: E402
from empire.plugins.ui.records import RecordsPage  # noqa: E402


def error(ident, project="stocks"):
    return {"id": ident, "project_id": project, "created_at": "2026-09-22T12:00:00+00:00",
            "version": "test", "stage": "decode", "error": "解析失败", "request_url": "https://example.com/data",
            "status_code": 200, "metadata": {"page": 3}, "body": "响应原文\n" * 20,
            "body_truncated": True, "original_bytes": 100000, "original_sha256": "a" * 64}


class Runtime:
    def __init__(self):
        self.calls = []
        self.values = []
        self.clear = Future()
        self.read = None
        self.revision = "1"

    def invoke(self, *args):
        self.calls.append(args)
        if args[1] == "clear_errors":
            return self.clear
        if self.read is not None:
            return self.read
        result = Future()
        if args[1] == "list_error_summaries":
            _, _, _, offset, limit, known = args
            changed = known != self.revision
            summaries = [{key: row.get(key) for key in (
                "id", "project_id", "created_at", "stage", "error", "status_code")}
                for row in self.values[offset:offset + limit]] if changed else []
            result.set_result({"revision": self.revision, "total": len(self.values),
                               "offset": offset, "limit": limit,
                               "changed": changed, "rows": deepcopy(summaries)})
        elif args[1] == "get_error":
            result.set_result(deepcopy(next((row for row in self.values if row["id"] == args[3]), None)))
        else:
            result.set_result(deepcopy(self.values))
        return result


@pytest.fixture
def page_factory():
    app = QApplication.instance() or QApplication([])
    pages = []

    def create(kind="errors"):
        runtime = Runtime()
        page = RecordsPage(SimpleNamespace(runtime=runtime, cfg={}), kind)
        page.timer.stop()
        page.set_projects([{"id": "stocks", "name": "股票列表"}, {"id": "news", "name": "财经新闻"}])
        pages.append(page)
        return page, runtime

    yield create
    for page in pages:
        page.deleteLater()
    app.processEvents()


def select(page, row):
    page.table.setCurrentCell(row, 0)
    page.table.selectionModel().select(page.table.model().index(row, 0),
                                      QItemSelectionModel.SelectionFlag.ClearAndSelect |
                                      QItemSelectionModel.SelectionFlag.Rows)


def test_error_view_shows_bounded_sample_metadata_without_auto_clearing(page_factory):
    page, runtime = page_factory()
    runtime.values = [error("first")]
    page.reload()
    page.tick()
    assert page.table.rowCount() == 1
    assert not page.clear_button.isEnabled()
    select(page, 0)
    page.tick()
    content = page.detail.toPlainText()
    assert "09-22 20:00:00" in content
    assert "响应原文" in content and "100000 字节" in content
    assert '"page": 3' in content and "样本截断：是" in content
    assert "a" * 64 in content
    assert "应用版本：test" in content
    assert not page.clear_button.isEnabled()
    page.clear_selected()
    assert not any(call[1] == "clear_errors" for call in runtime.calls)
    assert page.project.findData("unknown") >= 0
    assert runtime.calls[0] == (
        "collection.records", "list_error_summaries", "stocks", 0, 50, None)
    assert any(call == ("collection.records", "get_error", "stocks", "first")
               for call in runtime.calls)


def test_error_pages_and_unchanged_poll_do_not_reload_full_details(page_factory):
    page, runtime = page_factory()
    runtime.values = [error(str(index)) for index in range(120)]
    page.reload()
    page.tick()
    assert page.table.rowCount() == 50 and page.next.isEnabled()
    assert page.status.text().startswith("共 120 条")
    calls = len(runtime.calls)
    page.reload()
    assert runtime.calls[calls] == (
        "collection.records", "list_error_summaries", "stocks", 0, 50, "1")
    page.tick()
    assert page.table.rowCount() == 50
    assert not any(call[1] == "get_error" for call in runtime.calls)
    page.move(50)
    assert runtime.calls[-1] == (
        "collection.records", "list_error_summaries", "stocks", 50, 50, None)
    page.tick()
    assert page.offset == 50 and page.previous.isEnabled() and page.next.isEnabled()
    select(page, 0)
    page.tick()
    assert runtime.calls[-1][1] in {"get_error", "list_error_summaries"}
    assert "响应原文" in page.detail.toPlainText()


def test_precise_clear_requires_verified_selection_and_preserves_new_arrivals(page_factory):
    page, runtime = page_factory()
    page.records = [error("old-a"), error("old-b")]
    page.render()
    select(page, 0)
    page.verified.setChecked(True)
    assert page.clear_button.isEnabled()
    page.clear_selected()
    assert runtime.calls[-1] == ("collection.records", "clear_errors", "stocks", ["old-a"])
    assert not page.clear_button.isEnabled()
    page.records.insert(0, error("new-arrival"))
    page.render()
    runtime.clear.set_result(1)
    page.tick()
    assert [r["id"] for r in page.records] == ["new-arrival", "old-b"]
    assert not page.verified.isChecked()
    assert "已清除 1 条" in page.feedback.text()
    assert len([call for call in runtime.calls if call[1] == "clear_errors"]) == 1


def test_changing_selection_revokes_verification_and_refresh_preserves_text_selection(page_factory):
    page, runtime = page_factory()
    page.records = runtime.values = [error("a"), error("b")]
    page.render()
    select(page, 0)
    page.verified.setChecked(True)
    cursor = page.detail.textCursor()
    cursor.setPosition(5)
    cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 5)
    page.detail.setTextCursor(cursor)
    selected_text = page.detail.textCursor().selectedText()
    page.records.insert(0, error("new"))
    page.render()
    assert page.selected_ids() == {"a"}
    assert page.verified.isChecked()
    assert page.detail.textCursor().selectedText() == selected_text
    select(page, 2)
    assert not page.verified.isChecked()
    assert not page.clear_button.isEnabled()


def test_project_change_discards_stale_query_and_never_deletes_another_project(page_factory):
    page, runtime = page_factory()
    runtime.read = Future()
    page.reload()
    old = runtime.read
    old.set_running_or_notify_cancel()
    page.project.setCurrentIndex(page.project.findData("news"))
    old.set_result([error("wrong-project")])
    runtime.read = None
    runtime.values = [error("news-error", "news")]
    page.reload()
    page.tick()
    assert [r["id"] for r in page.records] == ["news-error"]
    assert any(call == ("collection.records", "list_error_summaries", "news", 0, 50, None)
               for call in runtime.calls)
    assert not page.verified.isChecked()


def test_archive_tab_uses_separate_history_and_shows_replay_status(page_factory):
    page, runtime = page_factory("archives")
    runtime.values = [{"id": "archive", "project_id": "stocks", "created_at": "2026-09-22T12:00:00+00:00",
                       "status": "replayed", "snapshot_id": "batch-id",
                       "processed_count": 5566, "written_count": 0,
                       "started_at": "2026-09-22T12:00:00+00:00", "finished_at": "2026-09-22T12:01:01+00:00"}]
    page.reload()
    page.tick()
    assert runtime.calls[-1] == ("collection.records", "list_archives", "stocks")
    assert page.table.item(0, 1).text() == "已确认重放"
    assert page.table.item(0, 2).text() == "5566"
    assert page.table.item(0, 3).text() == "0"
    assert page.clear_button.isHidden()
    select(page, 0)
    page.tick()
    assert "状态：已确认重放" in page.detail.toPlainText()
    assert "开始：09-22 20:00:00    结束：09-22 20:01:01（北京时间）" in page.detail.toPlainText()
    assert "数据批次：batch-id" in page.detail.toPlainText()
    assert "已处理记录：5566    业务写入记录：0" in page.detail.toPlainText()
    assert "确认无需写入：5566" in page.detail.toPlainText()
    assert "入库条数" not in page.detail.toPlainText()
    assert "失败原因：无" in page.detail.toPlainText()
    assert '"snapshot_id"' not in page.detail.toPlainText()
    assert page.table.horizontalHeader().sectionResizeMode(0) == QHeaderView.ResizeMode.ResizeToContents
    assert page.table.horizontalHeader().sectionResizeMode(4) == QHeaderView.ResizeMode.Stretch


def test_records_stop_polling_during_shutdown(page_factory):
    page, runtime = page_factory()
    page.shell.shutting_down = True
    page.reload()
    page.tick()
    assert runtime.calls == []
    assert not page.timer.isActive()
    assert record_time(None) == "—"


def test_partial_download_displays_unknown_original_and_observed_size(page_factory):
    page, runtime = page_factory()
    page.records = runtime.values = [{**error("partial"), "original_bytes": None,
                                      "original_sha256": None, "observed_bytes": 2097153,
                                      "body_complete": False, "sample_sha256": "b" * 64}]
    page.render()
    select(page, 0)
    page.tick()
    content = page.detail.toPlainText()
    assert "原文长度：未知（未完整读取）" in content
    assert "原文 SHA-256：未知（未完整读取）" in content
    assert "已读正文：2097153 字节" in content
    assert "脱敏样本 SHA-256：" + "b" * 64 in content


@pytest.mark.parametrize("width,height", [(880, 720), (1320, 900)])
def test_paginated_error_layout_keeps_navigation_and_actions_visible(page_factory, width, height):
    from empire.desktop.theme import STYLE

    page, runtime = page_factory()
    for name in ("msyh.ttc", "msyhbd.ttc", "segoeui.ttf"):
        font = Path("C:/Windows/Fonts") / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    runtime.values = [error(str(index)) for index in range(120)]
    page.setStyleSheet(STYLE)
    page.resize(width, height)
    page.show()
    page.reload()
    page.tick()
    QApplication.processEvents()
    assert page.table.geometry().bottom() < page.status.geometry().top()
    assert page.previous.isVisible() and page.next.isVisible()
    assert page.next.geometry().bottom() <= page.height()
    assert page.clear_button.geometry().bottom() <= page.height()
    target = Path(__file__).resolve().parents[1] / "artifacts" / f"error-records-{width}.png"
    target.parent.mkdir(exist_ok=True)
    assert page.grab().save(str(target))
