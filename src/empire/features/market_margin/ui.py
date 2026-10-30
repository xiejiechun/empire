"""Catalog metadata; task preview uses the formal bounded query capability."""

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.market_margin.contract import PROJECT, TABLES
from empire.plugins.ui.plugin import UiPlugin


class MarketMarginUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.market_margin",
        "市场融资融券浏览",
        provides=("ui.pages.market_margin",),
        description="按日期和来源市场名称浏览",
    )

    def create_pages(self):
        return (
            PageContribution(
                "market_margin",
                "市场融资融券",
                "数据浏览",
                53,
                "2010年起来源市场汇总；金额元、数量股、比例小数",
                database_tables=TABLES,
                catalogued=True,
                category="融资融券",
                source="同花顺",
                cache_policy="lru",
                management=NavigationTarget("collection", NavigationContext(task_id=PROJECT)),
            ),
        )
