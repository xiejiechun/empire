"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.listings.contract import PROJECT
from empire.plugins.ui.plugin import UiPlugin


class ListingUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.listings', '上市与发行资料界面', provides=('ui.pages.listings',), description='按需创建上市资料与历史沿革查询')

    def create_pages(self):
        return (PageContribution('listings', '上市与发行资料', '数据浏览', 20, '首次上市日期、发行价格、募资及历史沿革', database_tables=('stock_listing',), catalogued=True, category='证券基础', source='同花顺', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
