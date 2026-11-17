"""Task-owned metadata; React owns forms and asynchronous preview state."""

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.etf_fundamentals.contract import PROJECTS
from empire.plugins.ui.plugin import UiPlugin


class Ui(UiPlugin):
    manifest = PluginManifest(
        "ui.etf_fundamentals", "ETF份额与净值组件", provides=("ui.pages.etf_fundamentals",)
    )

    def create_pages(self):
        return tuple(
            PageContribution(
                page,
                title,
                "数据浏览",
                40400 + i,
                description,
                database_tables=tables,
                catalogued=True,
                category="基金数据",
                source=source,
                cache_policy="lru",
                management=NavigationTarget("collection", NavigationContext(task_id=PROJECTS[i])),
            )
            for i, (page, title, description, source, tables) in enumerate(
                (
                    (
                        "etf_sse_shares",
                        "上交所ETF每日份额",
                        "完整普通及交易货币基金来源日集合",
                        "上交所",
                        ("etf_daily_share", "etf_share_day"),
                    ),
                    (
                        "etf_szse_shares",
                        "深交所ETF每日份额",
                        "导出文件精确份额，次日复核",
                        "深交所",
                        ("etf_daily_share", "etf_share_day"),
                    ),
                    (
                        "etf_ttjj_nav",
                        "ETF历史净值明细",
                        "完整七列；货币收益与净值分列",
                        "天天基金",
                        ("etf_daily_nav", "etf_nav_year"),
                    ),
                )
            )
        )
