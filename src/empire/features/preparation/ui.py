"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution
from empire.plugins.ui.plugin import UiPlugin


class PreparationUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.preparation', '数据准备进度界面', provides=('ui.pages.preparation',), description='要准备的数据、当前进度和剩余工作')

    def create_pages(self):
        return (PageContribution('preparation', '数据准备', '数据准备', top_level=True, cache_policy='lru'),)
