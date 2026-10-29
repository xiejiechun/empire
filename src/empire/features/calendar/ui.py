"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.ui.plugin import UiPlugin


class CalendarUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.calendar', '交易日历界面', provides=('ui.pages.calendar',), autostart=True, description='交易日历界面的独立页面贡献')

    def create_pages(self):
        return (PageContribution('calendar', '交易日历', '数据浏览', 2, '巨潮 A 股交易日、休市日与月份完整性', catalogued=True, database_tables=('trade_calendar',), category='基础数据', source='巨潮资讯', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='cninfo-calendar'))),)
