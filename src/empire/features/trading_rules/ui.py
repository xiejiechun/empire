"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.trading_rules.contract import KINDS, project
from empire.plugins.ui.plugin import UiPlugin


class RuleUiPlugin(UiPlugin):

    def __init__(self, kind):
        self.kind = kind
        self.manifest = PluginManifest('ui.rules_' + kind, KINDS[kind] + '界面', provides=('ui.pages.rules_' + kind,))

    def create_pages(self):
        return (PageContribution('rules_' + self.kind, KINDS[self.kind], '数据浏览', 20, '规则生效段、数值及官方依据', database_tables=('trading_rule_value', 'trading_rule_citation'), catalogued=True, category='交易费用' if self.kind in ('stamp_duty', 'transfer_fee') else '交易规则', source='官方规则', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id=project(self.kind)))),)
