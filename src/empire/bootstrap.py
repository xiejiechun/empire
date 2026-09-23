from dataclasses import replace

from empire.core.manager import PluginManager
from empire.plugins.collection.control import CollectionControl, CollectionTask
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.collectors.cninfo_calendar import CninfoCalendarCollector
from empire.plugins.collectors.sina_news import SinaNewsCollector
from empire.plugins.collectors.sina_universe import SinaUniverseCollector
from empire.plugins.data.news import NewsDataPlugin
from empire.plugins.data.stocks import StockDataPlugin
from empire.plugins.data.trade_calendar import CalendarDataPlugin
from empire.plugins.infra.http import HttpPlugin
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
        HttpPlugin(cfg["rate_groups"]),
        ArchivePlugin(cfg["archive"]), IngestPlugin(cfg["ingest"]),
        StockDataPlugin(), SinaUniverseCollector(cfg.get("sina_universe", {})),
        NewsDataPlugin(), SinaNewsCollector(cfg.get("sina_news", {})),
        CalendarDataPlugin(), CninfoCalendarCollector(),
        CollectionControl([CollectionTask("sina-stocks", "新浪 A 股股票列表",
            "collector.sina_universe", "sina", "沪深北全量股票 · 代码 / 名称 / 统一代码 / 市场"),
            CollectionTask("sina-news", "新浪 7×24 小时全球实时财经新闻直播",
            "collector.sina_news", "sina", "最新窗口刷新与增量补采 · 正文 / 时间 / 分类 / 重点新闻",
            interval_minutes=1),
            CollectionTask("cninfo-calendar", "大 A 交易日期（巨潮资讯）",
            "collector.cninfo_calendar", "cninfo", "首次补齐历史 · 后续维护本月至下一年 12 月 · 交易日 / 休市日",
            interval_minutes=1440)]),
        WorkspaceUiPlugin(),
    ]
    for plugin in plugins:
        plugin.manifest = replace(plugin.manifest, autostart=True)
    return PluginManager(plugins)
