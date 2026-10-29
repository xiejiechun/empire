"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.ui.plugin import UiPlugin


class StockUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.stocks', '股票列表界面', provides=('ui.pages.stocks',), autostart=True, description='股票列表界面的独立页面贡献')

    def create_pages(self):
        return (PageContribution('stocks', '股票列表', '数据浏览', 0, '查找股票、筛选市场、复制数据 · Alt+2', catalogued=True, database_tables=('stock',), category='基础数据', source='同花顺 / 新浪财经', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='ths-stocks'))),)
