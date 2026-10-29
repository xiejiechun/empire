"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.ui.plugin import UiPlugin


class IndexPriceUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.index_prices', '指数日行情界面', provides=('ui.pages.index_prices',), description='按需创建日线范围查询')

    def create_pages(self):
        return (PageContribution('index_prices', '同花顺指数历史日行情', '数据浏览', 12, '历史开高低收及来源量额；逐年补缺、近期修订', database_tables=('index_daily_price', 'index_price_year'), catalogued=True, category='指数数据', source='同花顺', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='ths-index-prices'))),)
