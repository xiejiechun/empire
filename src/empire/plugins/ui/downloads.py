"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class DownloadSettingsUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.downloads', '下载资源界面', provides=('ui.pages.downloads',), autostart=True, description='管理同时下载数和共享临时内存预算')

    def create_pages(self):
        return (PageContribution('downloads', '下载资源', '采集管理', 5, '管理下载大小、内存缓冲和磁盘配额'),)
