"""Existing workspace/catalogue declarations; no page is created during assembly."""
from empire.contracts.ui import PageContribution


def catalog_page():
    from empire.features.data_browser.catalog import DataCatalogPage
    return PageContribution("catalog", "数据目录", DataCatalogPage, "数据浏览", -1,
                             "按业务分类与来源查找数据", cache_policy="lru")


def workspace_pages():
    from empire.plugins.ui.home import HomePage
    return (
        PageContribution("home", "总览", HomePage, "工作台", 0,
                         "数据更新与常用操作 · Alt+1", top_level=True, cache_policy="lru"),
        catalog_page(),
    )
