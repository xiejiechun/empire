"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class ReviewUi(UiPlugin):
    manifest = PluginManifest('ui.market_review', '市场复盘页面', provides=('ui.pages.market_review',))

    def create_pages(self):
        return (PageContribution('market_review', '市场复盘', '市场复盘', 62,
            '每日复盘整体行情、指数、个股样本成交额与含暗盘资金；其余分支逐项接入',
            top_level=True, category='市场复盘', source='远航 / 同花顺 / 东方财富 / 开盘啦',
            cache_policy='lru', database_tables=('trade_calendar', 'yuanhang_limit_pool',
                'yuanhang_limit_member', 'theme_daily', 'yuanhang_index_daily_price',
                'yuanhang_daily_price', 'graymarket_day', 'graymarket_daily',
                'industry', 'industry_member', 'collection_state')),)
