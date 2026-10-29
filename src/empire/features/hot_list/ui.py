"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.hot_list.contract import PROJECT
from empire.plugins.ui.plugin import UiPlugin


class HotListUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.hot_list', '龙虎榜浏览', provides=('ui.pages.hot_list',), description='按需创建日期与席位浏览')

    def create_pages(self):
        return (PageContribution('hot_list', '个股龙虎榜', '数据浏览', 50, '全部可得历史、原因与席位；来源缺失单独呈现', database_tables=('hot_list_day', 'hot_list_reason', 'hot_list_seat'), catalogued=True, category='交易事件', source='通达信', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
