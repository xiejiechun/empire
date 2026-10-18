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


def test_retry_editor_saves_one_hundred_without_refresh_clamping(page_factory):
    page = page_factory()
    assert page.retries.minimum() == 0 and page.retries.maximum() == 100
    page.retries.setValue(100)
    page.render()
    assert page.retries.value() == 100
    page.save_job()
    assert page.shell.runtime.calls[-1][3]["request_retries"] == 100


def test_archived_page_restores_selected_task_and_clears_removed_selection():
    from empire.plugins.ui.collection_views.archived import ArchivedTasksPage
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    page = ArchivedTasksPage(SimpleNamespace(runtime=runtime, cfg={}))
    page.timer.stop()
    try:
        page.data = snapshot()
        page.data['jobs'][0].update(source_name='新浪', category='证券基础')
        page.data['jobs'][0]['policy'].update(archived=True, enabled=False)
        page.data.update(total=1, offset=0)
        page.render()
        assert page._query_args()[4] == 'archived'
        assert not page.restore.isEnabled()
        page.tasks.selectRow(0)
        assert page.restore.isEnabled()
        page.restore.click()
        assert runtime.calls[-1] == ('collection.control', 'set_archived', 'stocks', False)
        page._finish_action()
        page.data.update(jobs=[], total=0)
        page.render()
        assert not page.restore.isEnabled() and page.tasks.rowCount() == 0
    finally:
        page.deleteLater()
        app.processEvents()


def test_capital_progress_shows_admitted_data_beyond_failed_frontier(page_factory):
    page = page_factory()
    page.data = snapshot()
    page.data['jobs'][0].update(active='run', unit_name='只股票', progress={
        'status': 'collecting', 'collected': 12, 'queued_records': 12, 'expected_count': 20,
        'continuous_collected': 0, 'processed_units': 6, 'total_units': 10,
        'failed_units': 1, 'current_security': 'SH:600962'})
    page.render_content()
    page._render_job_detail(page.data['jobs'][0])
    text = ' · '.join(field.text() for field in page.runtime_fields.values())
    assert '已入队 12 / 20 条' in text
    assert '连续已入队 0 条' in text
    assert '失败 1 只股票' in text and page.runtime_fields['current'].text() == 'SH:600962'
    assert page.progress.value() == 60


def test_proxy_default_and_full_schedule_column(page_factory):
    page = page_factory()
    page.data = snapshot()
    page.data['jobs'][0]['policy'].update(mode='interval', interval_seconds=2592000, enabled=False)
    page.render_content()
    page.resize(680, 560)
    page.show()
    QApplication.processEvents()
    assert page.route_mode.currentData() == 'proxy_fallback'
    assert page.task_menu.task_items['stocks'].text(1) == '已停用'
    assert '2,592,000 秒' in page.runtime_fields['plan'].text()
    assert page.runtime_fields['network'].text()
    assert page.task_menu.task_items['stocks'].parent() is not None


@pytest.mark.parametrize('unit', ['个指数', '只股票', '个行业', '股票日'])
def test_business_progress_is_independent_of_pages(page_factory, unit):
    page = page_factory()
    job = page.data['jobs'][0]
    job.update(unit_name=unit, active='run', progress=dict(
        completed_units=120, total_units=573, pages=4754, collected=90000))
    page._render_job_detail(job)
    assert page.runtime_fields['units'].text() == f'已处理 120 / 573 {unit}'
    assert '4,754' in page.runtime_fields['pages'].text()
    assert page.progress.value() == 20
    assert page.runtime_fields['next'].text() == '未启用自动执行'


def test_month_scope_is_not_divided_by_archive_pages(page_factory):
    page = page_factory()
    job = page.data['jobs'][0]
    job.update(active='run', progress=dict(total_months=12, pages=40))
    page._render_job_detail(job)
    assert page.runtime_fields['units'].text() == '本轮范围 12 个月；完成数未提供'
    assert page.progress.maximum() == 0
    job['progress'] = dict(completed_units=2)
    page._render_job_detail(job)
    assert '/ 0' not in page.runtime_fields['units'].text()


def test_action_buttons_have_balanced_rows(page_factory):
    page = page_factory()
    page.resize(680, 560)
    page.show()
    QApplication.processEvents()
    assert page.run_button.y() == page.pause_button.y()
    assert page.fresh_button.y() == page.archive_button.y()
    assert page.fresh_button.y() > page.run_button.y()
    assert abs(page.fresh_button.width() - page.archive_button.width()) <= 1


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
    assert tasks.task_menu.columnCount() == 2
    tasks.resize(1200, 700)
    QApplication.processEvents()
    assert tasks.task_split.orientation() == Qt.Orientation.Horizontal
    assert tasks.task_filters.getItemPosition(tasks.task_filters.indexOf(tasks.task_status))[0] == 0
    assert tasks.task_menu.task_items["stocks"].parent().isExpanded()


def test_task_sources_are_named_and_separate_from_business_categories(page_factory):
    page = page_factory()
    page.data['sources'] = ['sina']
    page.data['source_names'] = {'sina': '新浪财经'}
    page.data['jobs'][0].update(source_name='新浪财经', category='基础数据')
    page.render()
    assert page.task_source.itemText(page.task_source.findData('sina')) == '新浪财经'
    group = page.task_menu.group_items['sina']
    assert '新浪财经' in group.text(0)
    assert '基础数据' in page.task_menu.task_items['stocks'].toolTip(0)
    assert group.font(0).bold()


def test_source_parent_has_no_task_actions_and_keeps_draft(page_factory):
    page = page_factory()
    page.operation_feedback.setText('任务已启动')
    page.interval.setValue(37)
    group = page.task_menu.group_items['sina']
    page.task_menu.setCurrentItem(group)
    assert page.selected() is None
    assert '任务已启动' not in page.operation_feedback.text()
    assert not page.run_button.isEnabled() and not page.save_button.isEnabled()
    page.render()
    assert page.task_menu.currentItem() is group
    assert page.runtime_fields['count'].text() == '—'
    page.task_menu.select_task('stocks')
    assert page.interval.value() == 37 and 'stocks' in page.job_drafts


def test_menu_refresh_keeps_items_collapse_selection_and_live_state(page_factory):
    page = page_factory()
    menu = page.task_menu
    child = menu.task_items['stocks']
    group = child.parent()
    group.setExpanded(False)
    page.data['jobs'][0].update(active='run', progress={'status': 'awaiting_archive', 'collected': 50})
    page.render()
    assert menu.task_items['stocks'] is child
    assert not group.isExpanded()
    assert menu.selected_id() == 'stocks'
    assert page.runtime_fields['archive'].text() == '等待本轮归档确认'
    assert page.progress.maximum() == 0


def test_focused_task_opens_parent_and_restores_saved_draft(page_factory):
    page = page_factory()
    page.interval.setValue(37)
    page.task_menu.setCurrentItem(page.task_menu.group_items['sina'])
    page.apply_navigation_context(NavigationContext(task_id='stocks'))
    page.data = snapshot()
    page.render()
    assert page.selected()['id'] == 'stocks'
    assert page.interval.value() == 37
    assert page.task_menu.currentItem().parent().isExpanded()


def test_empty_menu_clears_stale_detail_and_actions(page_factory):
    page = page_factory()
    page.data['jobs'] = []
    page.render()
    assert page.task_menu.topLevelItemCount() == 0
    assert page.selected() is None
    assert page.runtime_fields['status'].text() == '—'
    assert not page.run_button.isEnabled()


def test_runtime_uses_last_run_and_keeps_full_plain_error(page_factory):
    page = page_factory()
    error = '<b>source failure</b>\n' * 80
    page.data['jobs'][0].update(last_status='error', error=error)
    page.data['history'] = [{'task_id': 'stocks', 'result': {'collected': 12, 'pages': 2},
                            'started_at': 100, 'finished_at': 150, 'error': error}]
    page.render()
    assert page.runtime_fields['count'].text() == '12 条'
    assert page.runtime_fields['error'].text() == error
    assert page.runtime_fields['error'].textFormat() == Qt.TextFormat.PlainText
    assert page.runtime_fields['start'].text() != '—'
    assert page.progress.value() == 0
    assert '整轮已确认' not in page.runtime_fields['archive'].text()


def test_failed_run_without_statistics_does_not_claim_zero_records(page_factory):
    page = page_factory()
    page.data['jobs'][0].update(last_status='error', error='网络失败')
    page.data['history'] = [{'task_id': 'stocks', 'result': {}, 'finished_at': 150}]
    page.render()
    assert page.runtime_fields['count'].text() == '暂无数量统计'
    assert page.runtime_fields['archive'].text() == '尚未确认本轮完成；已归档部分可查询'


def test_save_controls_only_show_on_configuration_tab(page_factory):
    page = page_factory()
    page.show()
    QApplication.processEvents()
    assert page.save_panel.isHidden()
    page.task_inspector.setCurrentIndex(1)
    assert not page.save_panel.isHidden()
    page.task_inspector.setCurrentIndex(0)
    assert page.save_panel.isHidden()
    page.task_inspector.setCurrentIndex(2)
    assert page.save_panel.isHidden()


def test_rules_switch_and_refresh_preserve_configuration_draft(page_factory):
    page = page_factory()
    page.data['jobs'][0].update(id='sina-news', name='财经新闻')
    page.render()
    page.retries.setValue(4)
    page.task_inspector.setCurrentIndex(2)
    page.show()
    QApplication.processEvents()
    browser = page.task_rules.browser
    assert 'finance_news' in browser.toPlainText()
    browser.verticalScrollBar().setValue(150)
    position = browser.verticalScrollBar().value()
    page.render()
    assert browser.verticalScrollBar().value() == position
    assert page.retries.value() == 4
    assert page.job_drafts['sina-news']['request_retries'] == 4
    assert not page.shell.runtime.calls
    page.data['jobs'][0].update(id='tdx-unlocks', name='大小非解禁')
    page.render()
    assert 'restricted_share_unlock' in browser.toPlainText()
    assert page.job_drafts['sina-news']['request_retries'] == 4


@pytest.mark.parametrize('width,height', [(880, 720), (1320, 900)])
def test_source_group_layout(page_factory, width, height):
    from pathlib import Path

    from PySide6.QtGui import QFontDatabase

    from empire.desktop.theme import STYLE
    for name in ('msyh.ttc', 'msyhbd.ttc', 'segoeui.ttf'):
        font = Path('C:/Windows/Fonts') / name
        if font.is_file():
            QFontDatabase.addApplicationFont(str(font))
    page = page_factory()
    first = page.data['jobs'][0]
    page.data['jobs'] = [dict(deepcopy(first), id=str(i), name=name, source_name=source,
                              category=category, rate_group=source) for i, (name, source, category) in enumerate([
        ('A股交易日历', '巨潮资讯', '基础数据'), ('沪深北股票列表', '新浪财经', '基础数据'),
        ('财经快讯', '新浪财经', '资讯'), ('历史停复牌', '通达信', '交易可实现性')])]
    page.setStyleSheet(STYLE)
    page.render()
    page.resize(width, height)
    page.show()
    QApplication.processEvents()
    assert page.task_menu.columnCount() == 2
    assert page.task_menu.topLevelItemCount() == 3
    assert page.task_menu.group_items['新浪财经'].childCount() == 2
    target = Path(__file__).resolve().parents[1] / 'artifacts' / f'task-sources-{width}.png'
    target.parent.mkdir(exist_ok=True)
    assert page.grab().save(str(target))


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
        assert [page.task_inspector.tabText(i) for i in range(page.task_inspector.count())] == ["运行详情", "任务配置", "采集规则"]
    if section != "history":
        assert not hasattr(page, "history_tabs")
    else:
        assert page.history_tabs.count() == 3
        assert "采集 100 条 · 归档 100 条 · 错误 300 条" in page.summary.text()
    assert hasattr(page, "task_menu") == (section == "tasks")
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
    page.task_menu.select_task("news")
    page.mode.setCurrentIndex(page.mode.findData("daily"))
    assert page.interval.isHidden() and not page.daily.isHidden()
    page.task_menu.select_task("stocks")
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


def test_source_gap_history_and_runtime_never_claim_complete(page_factory):
    notice = '有效报告已归档；2份债券名称为空；下次补采。'
    history = dict(run_id='gap', task_id='stocks', started_at=1, finished_at=9,
                   status='source_gap', error='', notice=notice,
                   result=dict(collected=12, source_gap_units=2, source_identity_gaps=2, failed_units=0))
    page = page_factory('history')
    page.data['history'] = [history]
    page.render()
    page.history_filter.setCurrentIndex(page.history_filter.findData('source_gap'))
    assert page.history.rowCount() == 1
    assert '来源限制与补采' in page.history_detail.toPlainText()
    assert notice in page.history_detail.toPlainText()
    assert '数据已通过校验' not in page.history_detail.toPlainText()
    task = page_factory()
    task.data['history'] = [history]
    task.data['jobs'][0].update(last_status='source_gap', notice=notice)
    task.render()
    assert '来源缺口' in task.runtime_fields['status'].text()
    assert task.runtime_fields['gaps'].text() == '2 只证券 / 2 份报告'
    assert notice == task.runtime_fields['error'].text()
    assert task.run_button.text() == '继续采集'
    assert '有效报告已确认归档' in task.runtime_fields['archive'].text()


def test_shutdown_stops_collection_polling(page_factory):
    page = page_factory()
    page.shell.shutting_down = True
    page.tick()
    assert page.shell.runtime.calls == []
    assert not page.timer.isActive()


def test_proxy_choices_survive_refresh_and_save_with_task_policy(page_factory):
    page = page_factory()
    assert page.route_mode.currentData() == "proxy_fallback"
    page.route_mode.setCurrentIndex(page.route_mode.findData("proxy_only"))
    page.render()
    assert page.route_mode.currentData() == "proxy_only"
    page.save_job()
    policy = page.shell.runtime.calls[-1][-1]
    assert policy["use_proxy"] is True and policy["proxy_fallback"] is False
    page.tick()
    assert not page.save_button.isEnabled()


def test_context_focus_preserves_filters_and_other_task_drafts(page_factory):
    page = page_factory()
    page.task_search.setText("原筛选")
    page.mode.setCurrentIndex(page.mode.findData("interval"))
    page.interval.setValue(37)
    assert "stocks" in page.job_drafts
    page.apply_navigation_context(NavigationContext(task_id="sina-news"))
    assert page.task_search.text() == "原筛选"
    assert page._query_args()[5] == 0
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
    assert page._query_args()[5] == 0
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
