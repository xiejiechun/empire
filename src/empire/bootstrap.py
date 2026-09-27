from dataclasses import replace

from empire.core.manager import PluginManager
from empire.core.redaction import Redactor
from empire.plugins.collection.control import CollectionControl, TaskContribution
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.collectors.cninfo_calendar import CninfoCalendarCollector
from empire.plugins.collectors.sina_news import SinaNewsCollector
from empire.plugins.collectors.sina_universe import SinaUniverseCollector
from empire.plugins.data.news import NewsDataPlugin
from empire.plugins.data.stocks import StockDataPlugin
from empire.plugins.data.trade_calendar import CalendarDataPlugin
from empire.plugins.infra.archive_confirmation import ArchiveConfirmationPlugin
from empire.plugins.infra.download_settings import DownloadSettingsPlugin
from empire.plugins.infra.http import HttpPlugin
from empire.plugins.infra.proxy_pool import ProxyPoolPlugin
from empire.plugins.ui.collection import CollectionUiPlugin
from empire.plugins.ui.downloads import DownloadSettingsUiPlugin
from empire.plugins.ui.help import HelpUiPlugin
from empire.plugins.ui.news import NewsUiPlugin
from empire.plugins.ui.proxies import ProxyUiPlugin
from empire.plugins.ui.stocks import StockUiPlugin
from empire.plugins.ui.system import SystemUiPlugin
from empire.plugins.ui.trade_calendar import CalendarUiPlugin
from empire.plugins.ui.workspace import WorkspaceUiPlugin


def build_manager(cfg: dict) -> PluginManager:
    # Explicit internal allowlist. There is no arbitrary package discovery.
    from empire.plugins.datasets.astock import DatasetPlugin
    from empire.plugins.infra.mysql_store import MySQLPlugin
    from empire.plugins.infra.redis_store import RedisPlugin
    from empire.plugins.pipeline.archive import ArchivePlugin
    from empire.plugins.pipeline.ingest import IngestPlugin

    plugins = [
        DatasetPlugin(), RedisPlugin(cfg["redis"]), MySQLPlugin(cfg["mysql"]),
        RecordsPlugin(secrets=tuple(
            cfg.get(section, {}).get("password", "") for section in ("redis", "mysql")
        )),
        ProxyPoolPlugin(), DownloadSettingsPlugin(), HttpPlugin(cfg["rate_groups"], cfg.get("http", {})),
        ArchivePlugin(cfg["archive"]), IngestPlugin(cfg["ingest"]), ArchiveConfirmationPlugin(),
        StockDataPlugin(cfg["redis"].get("namespace", "empire")),
        SinaUniverseCollector(cfg.get("sina_universe", {})),
        NewsDataPlugin(), SinaNewsCollector(cfg.get("sina_news", {})),
        CalendarDataPlugin(), CninfoCalendarCollector(),
        CollectionControl([TaskContribution("sina-stocks", "新浪 A 股股票列表",
            "collector.sina_universe", "sina", "沪深北全量股票 · 代码 / 名称 / 统一代码 / 市场",
            category="基础数据", source_name="新浪财经", parallel_downloads=True),
            TaskContribution("sina-news", "新浪 7×24 小时全球实时财经新闻直播",
            "collector.sina_news", "sina", "最新窗口刷新与增量补采 · 正文 / 时间 / 分类 / 重点新闻",
            interval_seconds=60, category="资讯", source_name="新浪财经",
            fresh_description="重新扫描最新窗口并建立增量基线，已有新闻保留；请先检查尚未处理的缺口。"),
            TaskContribution("cninfo-calendar", "大 A 交易日期（巨潮资讯）",
            "collector.cninfo_calendar", "cninfo", "首次补齐历史 · 后续维护本月至下一年 12 月 · 交易日 / 休市日",
            interval_seconds=86400, category="基础数据", source_name="巨潮资讯",
            fresh_description="从 1990-12 起重新核验全部月份至下一年 12 月；正常维护请用立即采集。")]),
        WorkspaceUiPlugin(), CollectionUiPlugin(), StockUiPlugin(), NewsUiPlugin(),
        CalendarUiPlugin(), SystemUiPlugin(), HelpUiPlugin(), ProxyUiPlugin(), DownloadSettingsUiPlugin(),
    ]
    for plugin in plugins:
        plugin.manifest = replace(plugin.manifest, autostart=True)
    return PluginManager(plugins, redactor=Redactor.from_config(cfg))
