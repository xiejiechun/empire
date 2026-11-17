"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.yuanhang.contract import TABLE_COLUMNS
from empire.plugins.ui.plugin import UiPlugin


class YuanhangUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.yuanhang', '远航历史行情页面', provides=('ui.pages.yuanhang',), description='按需创建日线、权息与三种股本浏览页面')

    def create_pages(self):
        return (PageContribution('yuanhang', '股票历史行情', '数据浏览', 60, '不复权日线、分红送转配股及历史股本', catalogued=True, category='行情数据', source='同花顺远航版', cache_policy='lru', database_tables=tuple(TABLE_COLUMNS), management=NavigationTarget('collection', NavigationContext(task_id='ths-yuanhang-prices'))),)
