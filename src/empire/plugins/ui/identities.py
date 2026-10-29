"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class IdentityUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.identities', '身份管理界面', provides=('ui.pages.identities',), description='平台身份、固定申请参数与上轮结果')

    def create_pages(self):
        return (PageContribution('identities', '身份管理', '采集管理', 5, '按平台管理节点身份，查看申请参数及上次结果', cache_policy='lru'),)
