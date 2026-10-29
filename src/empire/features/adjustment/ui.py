"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class AdjustmentUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.adjustment', '复权计算界面', provides=('ui.pages.adjustment',), description='按需计算与浏览，不启动网络任务')

    def create_pages(self):
        return (PageContribution('adjustment', '自算复权因子与行情', '数据浏览', 30, '完整查询范围的日K线、均线及前后复权；缺少复权输入时提示原因', catalogued=True, category='股票行情', source='自算', cache_policy='lru', database_tables=('stock_daily_quote', 'dividend_plan', 'rights_issue')),)
