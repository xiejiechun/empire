"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.capital_actions.contract import KINDS
from empire.plugins.ui.plugin import UiPlugin


class CapitalUiPlugin(UiPlugin):

    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.' + kind, KINDS[kind][0] + '界面', provides=('ui.pages.' + kind,), description='独立按需创建的通达信方案浏览')

    def create_pages(self):
        return (PageContribution(self.kind, KINDS[self.kind][0], '数据浏览', 4 + list(KINDS).index(self.kind), '通达信历史方案与证券关联', database_tables=(KINDS[self.kind][1],), catalogued=True, category='增发送配', source='通达信', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=KINDS[self.kind][2]))),)
