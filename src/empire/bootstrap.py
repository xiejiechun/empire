from dataclasses import replace

from empire.core.manager import PluginManager
from empire.core.redaction import Redactor
from empire.plugins.collection.control import CollectionControl, TaskContribution
from empire.plugins.collection.execution_rules import HISTORICAL_DAY_RULE
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.collectors.cninfo_calendar import CninfoCalendarCollector
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS, project
from empire.plugins.collectors.kaipanla_products import KaipanlaProductCollector
from empire.plugins.collectors.sina_news import SinaNewsCollector
from empire.plugins.collectors.sina_universe import SinaUniverseCollector
from empire.plugins.collectors.tdx_additional_issues import TdxAdditionalIssuesCollector
from empire.plugins.collectors.tdx_dividends import TdxDividendsCollector
from empire.plugins.collectors.tdx_rights_issues import TdxRightsIssuesCollector
from empire.plugins.collectors.tdx_suspensions import TdxSuspensionCollector
from empire.plugins.collectors.ths_industries import ThsIndustryCollector
from empire.plugins.collectors.ths_statements import ThsStatementCollector
from empire.plugins.data.capital_actions import CapitalDataPlugin
from empire.plugins.data.financial_statements import FinancialDataPlugin
from empire.plugins.data.industries import IndustryDataPlugin
from empire.plugins.data.kaipanla_products import KaipanlaProductDataPlugin
from empire.plugins.data.news import NewsDataPlugin
from empire.plugins.data.preparation import PreparationPlugin
from empire.plugins.data.stocks import StockDataPlugin
from empire.plugins.data.suspensions import SuspensionDataPlugin
from empire.plugins.data.trade_calendar import CalendarDataPlugin
from empire.plugins.datasets.capital_actions import KINDS
from empire.plugins.datasets.financial_statements import KINDS as FINANCIAL_KINDS
from empire.plugins.infra.archive_confirmation import ArchiveConfirmationPlugin
from empire.plugins.infra.download_settings import DownloadSettingsPlugin
from empire.plugins.infra.http import HttpPlugin
from empire.plugins.infra.proxy_pool import ProxyPoolPlugin
from empire.plugins.ui.capital_actions import CapitalUiPlugin
from empire.plugins.ui.collection import CollectionUiPlugin
from empire.plugins.ui.downloads import DownloadSettingsUiPlugin
from empire.plugins.ui.financial_statements import FinancialUiPlugin
from empire.plugins.ui.help import HelpUiPlugin
from empire.plugins.ui.industries import IndustryUiPlugin
from empire.plugins.ui.kaipanla_products import KaipanlaProductUiPlugin
from empire.plugins.ui.news import NewsUiPlugin
from empire.plugins.ui.preparation import PreparationUiPlugin
from empire.plugins.ui.proxies import ProxyUiPlugin
from empire.plugins.ui.stocks import StockUiPlugin
from empire.plugins.ui.suspensions import SuspensionsUiPlugin
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

    rate_groups = dict(cfg["rate_groups"])
    rate_groups.setdefault("ths", {"domains": ["10jqka.com.cn"], "min_interval_ms": 2000})
    rate_groups.setdefault('kaipanla', {'domains': ['longhuvip.com'], 'min_interval_ms': 2000})
    rate_groups.setdefault('eastmoney', {'domains': ['eastmoney.com'], 'min_interval_ms': 2000})
    rate_groups.setdefault('bse', {'domains': ['bse.cn'], 'min_interval_ms': 2000})
    plugins = [
        DatasetPlugin(), RedisPlugin(cfg["redis"]), MySQLPlugin(cfg["mysql"]),
        RecordsPlugin(secrets=tuple(
            cfg.get(section, {}).get("password", "") for section in ("redis", "mysql")
        )),
        ProxyPoolPlugin(), DownloadSettingsPlugin(), HttpPlugin(rate_groups, cfg.get("http", {})),
        ArchivePlugin(cfg["archive"]), IngestPlugin(cfg["ingest"]), ArchiveConfirmationPlugin(),
        StockDataPlugin(cfg["redis"].get("namespace", "empire")),
        IndustryDataPlugin(namespace=cfg['redis'].get('namespace', 'empire'),
                           archive_settings=cfg.get('archive', {})),
        ThsIndustryCollector(), IndustryUiPlugin(),
        *(KaipanlaProductDataPlugin(kind, namespace=cfg['redis'].get('namespace', 'empire')) for kind in PRODUCTS),
        *(KaipanlaProductCollector(kind) for kind in PRODUCTS),
        *(KaipanlaProductUiPlugin(kind) for kind in PRODUCTS),
        SinaUniverseCollector(cfg.get("sina_universe", {})),
        NewsDataPlugin(namespace=cfg["redis"].get("namespace", "empire")), SinaNewsCollector(cfg.get("sina_news", {})),
        CalendarDataPlugin(namespace=cfg["redis"].get("namespace", "empire"),
                           archive_settings=cfg.get("archive", {})), CninfoCalendarCollector(),
        SuspensionDataPlugin(namespace=cfg["redis"].get("namespace", "empire")), TdxSuspensionCollector(),
        *(CapitalDataPlugin(kind, namespace=cfg['redis'].get('namespace', 'empire'),
                            archive_settings=cfg.get('archive', {})) for kind in KINDS),
        TdxDividendsCollector(), TdxAdditionalIssuesCollector(), TdxRightsIssuesCollector(),
        *(CapitalUiPlugin(kind) for kind in KINDS),
        *(FinancialDataPlugin(kind, namespace=cfg['redis'].get('namespace', 'empire'),
                             archive_settings=cfg.get('archive', {})) for kind in FINANCIAL_KINDS),
        *(ThsStatementCollector(kind) for kind in FINANCIAL_KINDS),
        *(FinancialUiPlugin(kind) for kind in FINANCIAL_KINDS),
        CollectionControl([*(TaskContribution(project(kind), '开盘啦' + item.title,
            'collector.kaipanla_' + kind, 'kaipanla', item.note,
            category='高频行情', source_name='开盘啦', interval_seconds=86400,
            parallel_downloads=True, default_enabled=False,
            execution_rule=HISTORICAL_DAY_RULE,
            fresh_description='从 2021 年起逐证券日重新核验本项，保留已归档历史；普通采集补缺，每周回看最近五个交易日。')
            for kind, item in PRODUCTS.items()),
            TaskContribution('ths-industries', '同花顺当前行业',
            'collector.ths_industries', 'ths', '最新行业名单与全部成分股票 · 不保存变化历史',
            category='证券基础', source_name='同花顺', interval_seconds=86400,
            fresh_description='完整刷新当前行业和成分；已入队整轮先完成归档，不保留历史变化。'),
            *(TaskContribution('ths-' + kind, item[0] + '（同花顺）',
            'collector.ths_' + kind, 'ths', '逐证券完整历史 · 来源舍入金额 · 无公告日期',
            category='基本面', source_name='同花顺', interval_seconds=86400,
            fresh_description='从当前股票池首个证券重查全部历史；保留已归档报表。')
            for kind, item in FINANCIAL_KINDS.items()),*(TaskContribution(item[2], item[0] + '（通达信）',
            'collector.tdx_' + kind, 'tdx', '全部可得历史核验 · 单证券完整归档',
            category='增发送配', source_name='通达信',
            fresh_description='从当前来源完整范围重新核验，保留已归档历史；普通采集优先续跑已入队断点。')
            for kind, item in KINDS.items()), TaskContribution("sina-stocks", "新浪 A 股股票列表",
            "collector.sina_universe", "sina", "沪深北全量股票 · 代码 / 名称 / 统一代码 / 市场",
            category="基础数据", source_name="新浪财经", parallel_downloads=True),
            TaskContribution("sina-news", "新浪 7×24 小时全球实时财经新闻直播",
            "collector.sina_news", "sina", "最新窗口刷新与增量补采 · 正文 / 时间 / 分类 / 重点新闻",
            interval_seconds=60, category="资讯", source_name="新浪财经",
            fresh_description="重新扫描最新窗口并建立增量基线，已有新闻保留；请先检查尚未处理的缺口。"),
            TaskContribution("cninfo-calendar", "大 A 交易日期（巨潮资讯）",
            "collector.cninfo_calendar", "cninfo", "首次补齐历史 · 后续维护本月至下一年 12 月 · 交易日 / 休市日",
            interval_seconds=86400, category="基础数据", source_name="巨潮资讯",
            fresh_description="从 1990-12 起重新核验全部月份至下一年 12 月；正常维护请用立即采集。"),
            TaskContribution("tdx-suspensions", "沪深 A 股历史停复牌（通达信）",
            "collector.tdx_suspensions", "tdx", "2004-12-27 起逐自然日完整检查 · 停牌 / 复牌 / 全天或临停",
            interval_seconds=86400, category="交易可实现性", source_name="通达信",
            fresh_description="从 2004-12-27 起按自然月重新核验至今；保留已归档事件。")]),
        WorkspaceUiPlugin(), CollectionUiPlugin(), StockUiPlugin(), NewsUiPlugin(),
        CalendarUiPlugin(), SuspensionsUiPlugin(), SystemUiPlugin(), HelpUiPlugin(), ProxyUiPlugin(),
        DownloadSettingsUiPlugin(),
    ]
    plugins.extend([PreparationPlugin(
        (contribution for plugin in plugins
         for contribution in getattr(plugin, "preparation", ())), plugins
    ), PreparationUiPlugin()])
    for plugin in plugins:
        plugin.manifest = replace(plugin.manifest, autostart=True)
    return PluginManager(plugins, redactor=Redactor.from_config(cfg))
