"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.st_events.contract import KINDS, project
from empire.plugins.ui.plugin import UiPlugin


class StUiPlugin(UiPlugin):

    def __init__(self, kind):
        self.kind = kind
        self.manifest = PluginManifest('ui.st_' + kind, KINDS[kind][0] + '界面', provides=('ui.pages.st_' + kind,), description='独立按需创建ST事件浏览页')

    def create_pages(self):
        return (PageContribution('st_' + self.kind, KINDS[self.kind][0], '数据浏览', 20, '来源历史ST事件与缺名记录', database_tables=('security_st_event',), catalogued=True, category='交易状态', source='通达信', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
