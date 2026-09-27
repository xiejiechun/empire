from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class WorkspaceUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.workspace", "工作台与数据目录", provides=("ui.pages.workspace",), autostart=True,
        description="工作台与数据目录的独立页面贡献",
    )

    def create_pages(self):
        from empire.plugins.ui.catalog import DataCatalogPage
        from empire.plugins.ui.home import HomePage
        return (
            PageContribution("home", "总览", HomePage, "工作台", 0,
                             "数据更新与常用操作 · Alt+1", top_level=True, cache_policy="lru"),
            PageContribution("catalog", "数据目录", DataCatalogPage, "数据浏览", -1,
                             "按业务分类与来源查找数据", cache_policy="lru"),
        )
