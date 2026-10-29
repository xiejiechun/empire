"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.ths_capital.contract import PROJECT, TABLES
from empire.plugins.ui.plugin import UiPlugin


class CapitalPageUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.ths_capital', '公司资本运作界面', provides=('ui.pages.ths_capital',))

    def create_pages(self):
        return (PageContribution('ths_capital', '公司资本运作', '数据浏览', 51, '融资、募投、收购、投资、参股IPO、转让、关联交易及质押解冻', database_tables=TABLES, catalogued=True, category='公司行动', source='同花顺', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=PROJECT))),)
