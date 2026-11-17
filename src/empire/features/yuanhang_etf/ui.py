"""Task-owned ETF navigation metadata; Electron supplies the preview shell."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.yuanhang_etf.contract import CATALOG_PROJECT, LATEST_PROJECT, PRICE_PROJECT
from empire.plugins.ui.plugin import UiPlugin


class EtfUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.yuanhang_etf', '远航ETF组件', provides=('ui.pages.yuanhang_etf',))

    def create_pages(self):
        return tuple(PageContribution(page, title, '数据浏览', 40300+i, description,
            database_tables=tables, catalogued=True, category='基金数据', source='同花顺远航版', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=project)))
            for i, (page, project, title, description, tables) in enumerate((
                ('yuanhang_etfs', CATALOG_PROJECT, 'ETF目录', '原生完整目录、市场和名称', ('yuanhang_etf',)),
                ('yuanhang_etf_prices', PRICE_PROJECT, 'ETF日K', '不复权日K与来源缺值', ('yuanhang_etf_daily_price', 'yuanhang_etf_price_year')),
                ('yuanhang_etf_latest', LATEST_PROJECT, 'ETF最新行情', '仅Redis最新值；来源报价时间及净值日期未知', ()),
            )))
