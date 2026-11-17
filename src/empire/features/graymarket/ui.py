"""Catalog metadata; task preview uses the formal bounded query capability."""

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.graymarket.contract import PROJECT, TABLES
from empire.plugins.ui.plugin import UiPlugin


class GraymarketUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.graymarket",
        "明盘暗盘资金榜浏览",
        provides=("ui.pages.graymarket",),
        description="按交易日和证券浏览",
    )

    def create_pages(self):
        return (
            PageContribution(
                "graymarket",
                "明盘暗盘资金榜",
                "数据浏览",
                52,
                "2026-05-11起完整个股日榜；模型估算金额元、比例小数",
                database_tables=TABLES,
                catalogued=True,
                category="资金流向",
                source="东方财富",
                cache_policy="lru",
                management=NavigationTarget("collection", NavigationContext(task_id=PROJECT)),
            ),
        )
