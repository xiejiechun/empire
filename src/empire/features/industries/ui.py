"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.ui.plugin import UiPlugin


class IndustryUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.industries', '当前行业界面', provides=('ui.pages.industries',), description='按需创建的行业及成分浏览')

    def create_pages(self):
        return (PageContribution('industries', '同花顺当前行业', '数据浏览', 10, '最新行业名单与成分股票，不保存变化历史', database_tables=('industry', 'industry_member'), catalogued=True, category='证券基础', source='同花顺', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='ths-industries'))),)
