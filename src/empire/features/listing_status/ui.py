"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.listing_status.contract import PROJECT
from empire.plugins.ui.plugin import UiPlugin


class ListingStatusUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.listing_status', '暂停恢复终止上市界面', provides=('ui.pages.listing_status',), description='独立按需创建事件浏览页')

    def create_pages(self):
        return (PageContribution('listing_status', '暂停恢复终止上市', '数据浏览', 20, '沪深A股来源事件、日期及说明', database_tables=('security_listing_event',), catalogued=True, category='证券基础', source='通达信', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
