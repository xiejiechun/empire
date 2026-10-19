"""Independent charts for bounded day series; trades remain time-window cursor pages."""
from functools import partial

from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.kaipanla.contract import PRODUCTS, project
from empire.features.kaipanla.product_page import ProductPage
from empire.features.kaipanla.storage_contract import dataset_tables
from empire.plugins.ui.plugin import UiPlugin


def create_product_page(shell, kind):
    if kind == 'quote':
        from empire.features.kaipanla.quote_page import QuotePage
        return QuotePage(shell, kind)
    return ProductPage(shell, kind)


class KaipanlaProductUiPlugin(UiPlugin):
    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.kaipanla_' + kind, PRODUCTS[kind].title + '界面', provides=('ui.pages.kaipanla_' + kind,))

    def create_pages(self):
        item = PRODUCTS[self.kind]
        return (PageContribution('kaipanla_' + self.kind, '开盘啦' + item.title,
            partial(create_product_page, kind=self.kind), '数据浏览', 11, item.note,
            database_tables=dataset_tables(self.kind), catalogued=True, category='高频行情', source='开盘啦',
            cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
