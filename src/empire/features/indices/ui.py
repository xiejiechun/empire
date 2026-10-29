"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.ui.plugin import UiPlugin


class IndexUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.indices', '当前指数界面', provides=('ui.pages.indices',), description='按需创建指数目录与成分浏览')

    def create_pages(self):
        return (PageContribution('indices', '同花顺当前指数及成分', '数据浏览', 11, '当前目录及成分；允许交叉归属，来源暂无单独标注', database_tables=('stock_index', 'stock_index_member'), catalogued=True, category='指数数据', source='同花顺', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='ths-indices'))),)
