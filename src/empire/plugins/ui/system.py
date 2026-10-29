"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class SystemUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.system', '系统管理界面', provides=('ui.pages.system',), autostart=True, description='系统管理界面的独立页面贡献')

    def create_pages(self):
        return (PageContribution('system', '运行状态', '系统设置', 0, '服务连接与归档状态', cache_policy='lru'), PageContribution('plugins', '插件管理', '系统设置', 1, '按功能分类维护内部插件', cache_policy='lru'))
