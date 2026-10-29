"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.performance.contract import UNIT_KINDS as KINDS
from empire.features.performance.contract import project
from empire.plugins.ui.plugin import UiPlugin


class PerformanceUiPlugin(UiPlugin):

    def __init__(self, kind):
        super().__init__()
        self.kind = kind
        self.manifest = PluginManifest('ui.tdx_' + kind, KINDS[kind][0] + '界面', provides=('ui.pages.tdx_' + kind,), description='按需创建的来源报告阅读与结构化查询')

    def create_pages(self):
        item = KINDS[self.kind]
        return (PageContribution(self.kind, item[0], '数据浏览', 50, '通达信财报解读；源端缺值与日期限制保持原值', database_tables=(item[1],), catalogued=True, category=item[3], source='通达信', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
