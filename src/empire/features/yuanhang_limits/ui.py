"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.yuanhang_limits.contract import TABLE_COLUMNS, project
from empire.plugins.ui.plugin import UiPlugin


class LimitsUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.yuanhang_limits', '远航涨跌停分析页面', provides=('ui.pages.yuanhang_limits',))

    def create_pages(self):
        return (PageContribution('yuanhang_limits', '远航涨跌停分析', '数据浏览', 61, '涨停板、涨停冲刺、连板池、炸板池、跌停板及原因', catalogued=True, category='涨跌停分析', source='同花顺远航版', cache_policy='lru', database_tables=tuple(TABLE_COLUMNS), management=NavigationTarget('collection', NavigationContext(task_id=project('limit_up_pool')))),)
