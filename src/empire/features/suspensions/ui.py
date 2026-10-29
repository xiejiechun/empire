"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.ui.plugin import UiPlugin


class SuspensionsUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.suspensions', '历史停复牌界面', provides=('ui.pages.suspensions',), autostart=True, description='通达信沪深 A 股历史停复牌来源记录浏览')

    def create_pages(self):
        return (PageContribution('suspensions', '历史停复牌', '数据浏览', 3, '通达信沪深 A 股停复牌时间、来源说明及原因', catalogued=True, database_tables=('suspension_event',), category='交易可实现性', source='通达信', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='tdx-suspensions'))),)
