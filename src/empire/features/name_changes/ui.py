"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.name_changes.contract import KINDS, project
from empire.plugins.ui.plugin import UiPlugin


class NameUiPlugin(UiPlugin):

    def __init__(self, kind):
        self.kind = kind
        self.manifest = PluginManifest('ui.names_' + kind, KINDS[kind][0] + '界面', provides=('ui.pages.names_' + kind,), description='独立按需创建更名事件浏览页')

    def create_pages(self):
        return (PageContribution('names_' + self.kind, KINDS[self.kind][0], '数据浏览', 20, '来源历史更名事件与缺名记录', database_tables=('security_name_change',), catalogued=True, category='证券基础', source='通达信', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
