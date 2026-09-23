from empire.contracts.plugin import PluginManifest
from empire.contracts.ui import PageContribution


class WorkspaceUiPlugin:
    manifest = PluginManifest(
        "ui.workspace", "研究工作台界面", provides=("ui.pages",), autostart=True,
        description="工作台、数据中心、采集管理和系统管理页面",
    )

    def __init__(self):
        self.active = False

    async def start(self, context):
        from empire.plugins.ui.collection import CollectionPage
        from empire.plugins.ui.help import StorageHelpPage
        from empire.plugins.ui.home import HomePage
        from empire.plugins.ui.news import NewsPage
        from empire.plugins.ui.stocks import StockListPage
        from empire.plugins.ui.system import PluginsPage, SystemStatusPage
        from empire.plugins.ui.trade_calendar import TradeCalendarPage
        self.active = True
        return {"ui.pages": (
            PageContribution("home", "总览", HomePage, "工作台", 0, "数据更新与常用操作 · Alt+1"),
            PageContribution("stocks", "股票列表", StockListPage, "数据中心", 0, "查找股票、筛选市场、复制数据 · Alt+2"),
            PageContribution("news", "财经快讯", NewsPage, "数据中心", 1, "新浪 7×24 新闻、搜索与重点筛选"),
            PageContribution("calendar", "交易日历", TradeCalendarPage, "数据中心", 2, "巨潮 A 股交易日、休市日与月份完整性"),
            PageContribution("collection", "采集任务", lambda shell: CollectionPage(shell, section="tasks"),
                             "采集管理", 0, "执行采集、管理更新计划 · Alt+3"),
            PageContribution("history", "运行记录", lambda shell: CollectionPage(shell, section="history"),
                             "采集管理", 1, "查看完成记录和失败原因"),
            PageContribution("sites", "网站频控", lambda shell: CollectionPage(shell, section="sites"),
                             "系统管理", 0, "管理跨任务共享的网站请求频率"),
            PageContribution("system", "运行状态", SystemStatusPage, "系统管理", 1, "服务连接与归档状态"),
            PageContribution("plugins", "插件管理", PluginsPage, "系统管理", 2, "按功能分类维护内部插件"),
            PageContribution("help", "说明文档", StorageHelpPage, "系统管理", 3, "Redis、MySQL 表与配置参数说明"),
        )}

    async def stop(self):
        self.active = False

    def health(self):
        return {"pages": 10 if self.active else 0}
