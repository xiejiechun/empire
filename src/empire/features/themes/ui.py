"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.features.themes.repository import TABLE_COLUMNS
from empire.plugins.ui.plugin import UiPlugin


class ThemeUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.themes', '题材浏览界面', provides=('ui.pages.themes',))

    def create_pages(self):
        return (PageContribution('themes', '开盘啦题材库', '数据浏览', 80, '热度、排名、涨跌幅、涨停数量及七日日内变化', catalogued=True, category='题材数据', source='开盘啦', cache_policy='lru', database_tables=tuple(TABLE_COLUMNS), management=NavigationTarget('collection', NavigationContext(task_id='kaipanla-themes'))),)
