"""Index task previews owned by their three independent components."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.yuanhang_indices.contract import CATALOG_PROJECT, MEMBER_PROJECT, PRICE_PROJECT
from empire.plugins.ui.plugin import UiPlugin


class IndexUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.yuanhang_indices', '远航指数组件', provides=('ui.pages.yuanhang_indices',))

    def create_pages(self):
        return tuple(PageContribution(page, title, '数据浏览', 40200+i, description,
            database_tables=tables, catalogued=True, category='指数数据',
            source='同花顺' if i == 1 else '同花顺远航版', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=project)))
            for i, (page, project, title, description, tables) in enumerate((
                ('yuanhang_indices', CATALOG_PROJECT, 'A股指数', '原生目录、市场与名称', ('yuanhang_index',)),
                ('yuanhang_index_members', MEMBER_PROJECT, '指数成分', '同花顺网页当前成分；来源暂无正常显示为空', ('ths_index_member_state', 'ths_index_member')),
                ('yuanhang_index_prices', PRICE_PROJECT, '指数日K', '原生日K、来源缺值及覆盖范围', ('yuanhang_index_daily_price', 'yuanhang_index_price_year')),
            )))
