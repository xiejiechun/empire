from empire.contracts.plugin import PluginManifest
from empire.plugins.ui.plugin import UiPlugin


class WorkspaceUiPlugin(UiPlugin):
    manifest = PluginManifest(
        "ui.workspace", "工作台与数据目录", provides=("ui.pages.workspace",), autostart=True,
        description="工作台与数据目录的独立页面贡献",
    )

    def __init__(self, page_factory):
        super().__init__()
        if not callable(page_factory):
            raise ValueError('工作台须显式注入页面贡献工厂')
        self.page_factory = page_factory

    def create_pages(self):
        return self.page_factory()
