"""Catalog metadata; task preview uses the formal bounded query capability."""

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.industry_margin.contract import PROJECT, TABLES
from empire.plugins.ui.plugin import UiPlugin


class IndustryMarginUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.industry_margin",
        "行业融资融券浏览",
        provides=("ui.pages.industry_margin",),
        description="按日期和来源行业名称浏览",
    )

    def create_pages(self):
        return (
            PageContribution(
                "industry_margin",
                "行业融资融券",
                "数据浏览",
                52,
                "2016年起来源完整行业日期集合；融资亿元、融券万元与万股",
                database_tables=TABLES,
                catalogued=True,
                category="融资融券",
                source="通达信",
                cache_policy="lru",
                management=NavigationTarget("collection", NavigationContext(task_id=PROJECT)),
            ),
        )
