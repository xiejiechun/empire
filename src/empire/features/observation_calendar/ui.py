from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class ObservationUi(UiPlugin):
    manifest = PluginManifest('ui.observation_calendar', '多指标观察日历页面',
                              provides=('ui.pages.observation_calendar',))

    def create_pages(self):
        return (PageContribution('observation_calendar', '多指标观察日历', '研究分析', 63,
            '按月对照指数行情、融资融券与汇率日线，保留真实日期和缺值', top_level=True,
            category='研究分析', source='同花顺 / 巨潮资讯', cache_policy='lru',
            database_tables=('trade_calendar', 'yuanhang_index', 'yuanhang_index_daily_price', 'market_margin_daily', 'yuanhang_daily_price', 'fx_daily_price')),)
