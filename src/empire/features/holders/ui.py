"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.holders.contract import KINDS, project
from empire.plugins.ui.plugin import UiPlugin


class HolderUiPlugin(UiPlugin):

    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.' + kind, KINDS[kind][0] + '界面', provides=('ui.pages.' + kind,))

    def create_pages(self):
        return (PageContribution(self.kind, KINDS[self.kind][0], '数据浏览', 50, '当前报告期前十及退出名单；来源舍入、无公告日期', database_tables=('holder_report', 'holder_member'), catalogued=True, category='股东数据', source='同花顺', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
