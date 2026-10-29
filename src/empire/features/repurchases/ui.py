"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.repurchases.contract import PROJECT
from empire.plugins.ui.plugin import UiPlugin


class RepurchaseUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.repurchases', '股票回购界面', provides=('ui.pages.repurchases',), description='按需创建回购方案与详情')

    def create_pages(self):
        return (PageContribution('repurchases', '股票回购', '数据浏览', 30, '计划与累计回购；不推断股份注销', database_tables=('stock_repurchase_plan',), catalogued=True, category='公司行动', source='东方财富', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
