"""Headless catalog metadata; previews remain owned by the tasks."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.fx.contract import DAILY_PROJECT, TABLES
from empire.plugins.ui.plugin import UiPlugin


class FxUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.fx', '汇率行情浏览', provides=('ui.pages.fx',))

    def create_pages(self):
        return (PageContribution('fx', '汇率行情', '数据浏览', 53,
            '实时最新值在Redis；来源日K线在MySQL', database_tables=tuple(TABLES),
            catalogued=True, category='外汇数据', source='同花顺远航版', cache_policy='lru',
            management=NavigationTarget('collection', NavigationContext(task_id=DAILY_PROJECT))),)
