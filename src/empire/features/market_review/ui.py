"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class ReviewUi(UiPlugin):
    manifest = PluginManifest('ui.market_review', '市场复盘页面', provides=('ui.pages.market_review',))

    def create_pages(self):
        return (PageContribution('market_review', '市场复盘', '市场复盘', 62, '涨停炸板、封板率、连板梯队、最高板演变、题材轮动与热度', top_level=True, category='市场复盘', source='远航 / 开盘啦', cache_policy='lru', database_tables=('trade_calendar', 'yuanhang_limit_pool', 'yuanhang_limit_member', 'theme_daily')),)
