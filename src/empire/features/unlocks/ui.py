"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.ui.plugin import UiPlugin


class UnlockUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.tdx_unlocks', '大小非解禁界面', provides=('ui.pages.tdx_unlocks',))

    def create_pages(self):
        return (PageContribution('unlocks', '大小非解禁个股与明细', '数据浏览', 50, '按证券、解禁日期查询列表事实及共享股东明细', database_tables=('restricted_share_unlock', 'restricted_share_unlock_detail'), catalogued=True, category='股东数据', source='通达信', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='tdx-unlocks'))),)
