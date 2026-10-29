"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class HelpUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.help', '说明文档界面', provides=('ui.pages.help',), autostart=True, description='离线说明文档与分组目录')

    def create_pages(self):
        return (PageContribution('help', '说明文档', '说明文档', 0, '操作指引、分类数据手册、故障处理与维护参考 · F1', top_level=True, cache_policy='lru'),)
