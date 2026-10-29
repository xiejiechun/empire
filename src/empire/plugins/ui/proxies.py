"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class ProxyUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.proxies', '采集出口界面', provides=('ui.pages.proxies',), autostart=True, description='代理上下线、隔离与直连回退统计')

    def create_pages(self):
        return (PageContribution('proxies', '采集出口', '采集管理', 4, '代理出口状态和代理/直连请求统计', cache_policy='lru'),)
