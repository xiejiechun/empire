"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.ui.plugin import UiPlugin


class UnlockIndustryUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.tdx_unlock_industries', '大小非解禁行业界面', provides=('ui.pages.tdx_unlock_industries',))

    def create_pages(self):
        return (PageContribution('unlock_industries', '大小非解禁行业', '数据浏览', 51, '按解禁月份、行业查看数量、市值及比例', database_tables=('restricted_share_unlock_industry',), catalogued=True, category='股东数据', source='通达信', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='tdx-unlock-industries'))),)
