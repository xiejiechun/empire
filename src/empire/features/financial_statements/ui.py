"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.financial_statements.contract import KINDS
from empire.plugins.ui.plugin import UiPlugin


class FinancialUiPlugin(UiPlugin):

    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.' + kind, KINDS[kind][0] + '界面', provides=('ui.pages.' + kind,))

    def create_pages(self):
        return (PageContribution(self.kind, KINDS[self.kind][0], '数据浏览', 20 + list(KINDS).index(self.kind), '来源历史财报与金额精度', catalogued=True, category='基本面', source='同花顺', cache_policy='lru', database_tables=(KINDS[self.kind][2],), management=NavigationTarget('collection', NavigationContext(task_id='ths-' + self.kind))),)
