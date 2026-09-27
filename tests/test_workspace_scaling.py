import os
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402
from test_collection_ui import Runtime as CollectionRuntime  # noqa: E402
from test_collection_ui import snapshot  # noqa: E402
from test_navigation import Runtime  # noqa: E402

from empire.contracts.ui import PageContribution  # noqa: E402
from empire.desktop.window import MainWindow  # noqa: E402
from empire.plugins.collection.control import CollectionControl, TaskContribution  # noqa: E402
from empire.plugins.ui.catalog import DataCatalogPage  # noqa: E402
from empire.plugins.ui.collection_views.tasks import TasksPage  # noqa: E402


async def test_workspace_bounds_health_and_history_for_500_projects():
    specs = [TaskContribution(f"job-{i:03}", f"任务 {i}", "collector", f"site-{i % 5}", "内容",
                            category=f"category-{i % 2}") for i in range(500)]
    control = CollectionControl(specs)
    template = snapshot()["jobs"][0]
    control.state = {"jobs": {d.id: deepcopy(template) for d in specs},
                     "history": [{"task_id": d.id, "run_id": f"{d.id}-{n}", "status": "complete"}
                                 for n in range(100) for d in specs]}
    calls = []
    source = SimpleNamespace(health=lambda: calls.append(1) or {})
    control.context = SimpleNamespace(get=lambda _: source, optional=lambda _: source)
    control.http = SimpleNamespace(settings=AsyncMock(return_value=[]))
    result = await control.workspace("tasks", source="site-1", offset=25)
    assert result["total"] == 100 and result["counts"]["total"] == 500
    assert len(result["jobs"]) == len(result["history"]) == len(calls) == 25
    assert all(j["rate_group"] == "site-1" for j in result["jobs"])
    assert len({j["id"] for j in result["jobs"]}) == 25
    history = await control.workspace("history", project="job-001", offset=75)
    assert history["total"] == 100 and len(history["history"]) == 25
    assert all(h["task_id"] == "job-001" for h in history["history"])
    overview = await control.workspace("overview")
    assert len(overview["history"]) == 5 and not overview["jobs"]
    assert len(calls) == 25  # No hidden collector health probes for overview or history.
    empty = await control.workspace("tasks", query="not found", offset=9999)
    assert empty["jobs"] == [] and empty["offset"] == 0
    focused = await control.workspace(
        "tasks", query="not found", category="missing", offset=75, focus_task_id="job-499"
    )
    assert [job["id"] for job in focused["jobs"]] == ["job-499"]
    assert focused["focused_task_id"] == "job-499" and not focused["focus_missing"]
    missing = await control.workspace("tasks", focus_task_id="retired-task")
    assert missing["jobs"] == [] and missing["focus_missing"]


def test_hundreds_of_data_pages_stay_lazy_and_do_not_expand_navigation():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    runtime.contributions = [PageContribution("home", "工作台", lambda _: QLineEdit(), top_level=True),
                            PageContribution("catalog", "数据目录", DataCatalogPage, "数据浏览", -1)]
    runtime.contributions += [PageContribution(f"data-{i}", f"数据 {i}", lambda _: QLineEdit(),
                                              "数据浏览", i, catalogued=True,
                                              category=f"分类 {i % 4}", source=f"来源 {i % 5}")
                              for i in range(500)]
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        assert list(window.page_widgets) == ["home"]
        window.navigate("catalog")
        catalog = window.page_widgets["catalog"]
        assert catalog.table.rowCount() == 25 and catalog.pager.total == 500
        catalog.source.setCurrentIndex(catalog.source.findData("来源 1"))
        assert catalog.pager.total == 100
        catalog.change_page(75)
        assert catalog.table.rowCount() == 25 and not catalog.pager.next.isEnabled()
        catalog.table.selectRow(5)
        selected_id = catalog.entries[5].id
        catalog.open_selected()
        assert window.current_page_id == selected_id
        assert window.navigate("catalog")
        catalog = window.page_widgets["catalog"]
        assert catalog.source.currentData() == "来源 1" and catalog.offset == 75
        assert catalog.entries[catalog.table.currentRow()].id == selected_id
        window.navigate("data-499")
        assert window.subnav.count() == 2
        window.navigate("data-123")
        assert window.subnav.count() == 2
        assert set(window.page_widgets) == {
            "home", "catalog", selected_id, "data-499", "data-123"
        }
        # Removing a contribution preserves other visited pages and recovers navigation.
        runtime.contributions = [p for p in runtime.contributions if p.id != "data-123"]
        window.refresh()
        assert window.current_page_id == "home"
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_catalog_can_switch_between_already_visited_data_pages():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    runtime.contributions = [
        PageContribution("catalog", "数据目录", DataCatalogPage, "数据浏览", -1),
        PageContribution("stocks", "股票列表", lambda _: QLineEdit(), "数据浏览", 0,
                         catalogued=True, category="基础数据", source="新浪"),
        PageContribution("news", "财经快讯", lambda _: QLineEdit(), "数据浏览", 1,
                         catalogued=True, category="资讯", source="新浪"),
        PageContribution("calendar", "交易日历", lambda _: QLineEdit(), "数据浏览", 2,
                         catalogued=True, category="基础数据", source="巨潮"),
    ]
    window = MainWindow(runtime, {})
    window.timer.stop()
    try:
        for target in ("stocks", "calendar", "news", "stocks"):
            assert window.navigate("catalog")
            catalog = window.page_widgets["catalog"]
            row = next(i for i, entry in enumerate(catalog.entries) if entry.id == target)
            catalog.table.selectRow(row)
            catalog.open_selected()
            assert window.current_page_id == target
            assert window.pages.currentWidget() is window.page_containers[target]
    finally:
        runtime.closed.set()
        window.close()
        window.deleteLater()
        app.processEvents()


def test_task_draft_survives_page_change_and_empty_results_disable_actions():
    app = QApplication.instance() or QApplication([])
    page = TasksPage(SimpleNamespace(runtime=CollectionRuntime(), cfg={}))
    page.timer.stop()
    try:
        data = snapshot()
        data.update(total=500, offset=0, limit=25, categories=["基础数据"], sources=["sina"])
        page.data = data
        page.render()
        page.mode.setCurrentIndex(page.mode.findData("interval"))
        page.interval.setValue(37)
        page.change_page(25)
        assert not page.save_button.isEnabled()
        other = deepcopy(data)
        other["jobs"][0].update(id="other", name="另一任务")
        other["offset"] = 25
        page.data = other
        page.render()
        page.data = deepcopy(data)
        page.render()
        assert page.interval.value() == 37 and page.save_button.isEnabled()
        empty = deepcopy(data)
        empty.update(jobs=[], total=0)
        page.data = empty
        page.render()
        assert not page.save_button.isEnabled() and not page.run_button.isEnabled()
        assert page.job_drafts["stocks"]["interval_seconds"] == 37
    finally:
        page.deleteLater()
        app.processEvents()
