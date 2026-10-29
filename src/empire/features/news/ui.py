"""Headless page metadata; rendered widgets belong to the Electron frontend."""
from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import NavigationContext, NavigationTarget, PageContribution
from empire.plugins.ui.plugin import UiPlugin


class NewsUiPlugin(UiPlugin):
    manifest = PluginManifest('ui.news', '财经快讯界面', provides=('ui.pages.news',), autostart=True, description='财经快讯界面的独立页面贡献')

    def create_pages(self):
        return (PageContribution('news', '财经快讯', '数据浏览', 1, '新浪 7×24 新闻、搜索与重点筛选', catalogued=True, database_tables=('finance_news',), category='资讯', source='新浪财经', cache_policy='lru', management=NavigationTarget('collection', NavigationContext(task_id='sina-news'))),)
