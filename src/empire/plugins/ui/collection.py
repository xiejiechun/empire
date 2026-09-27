"""Collection management page contributions."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.collection_views.history import HistoryPage
from empire.plugins.ui.collection_views.sites import SitesPage
from empire.plugins.ui.collection_views.tasks import TasksPage
from empire.plugins.ui.plugin import UiPlugin


class CollectionUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.collection", "采集管理界面", provides=("ui.pages.collection",), autostart=True,
        description="采集管理界面的独立页面贡献",
    )

    def create_pages(self):
        return (
            PageContribution("collection", "采集任务", TasksPage,
                             "采集管理", 0, "执行采集、管理更新计划 · Alt+3"),
            PageContribution("history", "运行记录", HistoryPage,
                             "采集管理", 1, "查看完成记录和失败原因"),
            PageContribution("sites", "站点访问规则", SitesPage,
                             "采集管理", 2, "按出口 IP 管理同站点访问节奏"),
        )
