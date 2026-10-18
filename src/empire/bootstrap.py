from dataclasses import replace

from empire.contracts.holders import KINDS as HOLDER_KINDS
from empire.contracts.holders import project as holder_project
from empire.contracts.name_changes import KINDS as NAME_KINDS
from empire.contracts.name_changes import project as name_project
from empire.contracts.st_events import KINDS as ST_KINDS
from empire.contracts.st_events import project as st_project
from empire.contracts.tdx_performance import UNIT_KINDS as PERFORMANCE_KINDS
from empire.contracts.tdx_performance import project as performance_project
from empire.contracts.trading_rules import KINDS as RULE_KINDS
from empire.contracts.trading_rules import project as rule_project
from empire.core.manager import PluginManager
from empire.core.redaction import Redactor
from empire.plugins.collection.control import CollectionControl, TaskContribution
from empire.plugins.collection.records import RecordsPlugin
from empire.plugins.collection.task_defaults import HISTORICAL_DAY_DEFAULTS, TaskDefaults
from empire.plugins.collectors.cninfo_calendar import CninfoCalendarCollector
from empire.plugins.collectors.eastmoney_repurchase import RepurchaseCollector
from empire.plugins.collectors.kaipanla_kinds import PRODUCTS, project
from empire.plugins.collectors.kaipanla_products import KaipanlaProductCollector
from empire.plugins.collectors.rule_sources import RuleSources
from empire.plugins.collectors.sina_news import SinaNewsCollector
from empire.plugins.collectors.sina_universe import SinaUniverseCollector
from empire.plugins.collectors.tdx_additional_issues import TdxAdditionalIssuesCollector
from empire.plugins.collectors.tdx_dividends import TdxDividendsCollector
from empire.plugins.collectors.tdx_listing_status import TdxListingStatusCollector
from empire.plugins.collectors.tdx_name_changes import NameChangeCollector
from empire.plugins.collectors.tdx_performance import PerformanceCollector
from empire.plugins.collectors.tdx_rights_issues import TdxRightsIssuesCollector
from empire.plugins.collectors.tdx_st_events import StEventCollector
from empire.plugins.collectors.tdx_suspensions import TdxSuspensionCollector
from empire.plugins.collectors.tdx_unlock_industries import UnlockIndustryCollector
from empire.plugins.collectors.tdx_unlocks import UnlockCollector
from empire.plugins.collectors.ths_capital import CapitalPageCollector
from empire.plugins.collectors.ths_holders import HolderCollector
from empire.plugins.collectors.ths_index_prices import ThsIndexPriceCollector
from empire.plugins.collectors.ths_indices import ThsIndexCollector
from empire.plugins.collectors.ths_industries import ThsIndustryCollector
from empire.plugins.collectors.ths_listings import ThsListingCollector
from empire.plugins.collectors.ths_statements import ThsStatementCollector
from empire.plugins.collectors.ths_universe import ThsUniverseCollector
from empire.plugins.collectors.trading_rules import RuleCollector
from empire.plugins.data.adjustment import AdjustmentDataPlugin
from empire.plugins.data.capital_actions import CapitalDataPlugin
from empire.plugins.data.financial_statements import FinancialDataPlugin
from empire.plugins.data.holders import HolderDataPlugin
from empire.plugins.data.index_prices import IndexPriceDataPlugin
from empire.plugins.data.indices import IndexDataPlugin
from empire.plugins.data.industries import IndustryDataPlugin
from empire.plugins.data.kaipanla_products import KaipanlaProductDataPlugin
from empire.plugins.data.listing_status import ListingStatusDataPlugin
from empire.plugins.data.listings import ListingDataPlugin
from empire.plugins.data.name_changes import NameDataPlugin
from empire.plugins.data.news import NewsDataPlugin
from empire.plugins.data.preparation import PreparationPlugin
from empire.plugins.data.repurchases import RepurchaseDataPlugin
from empire.plugins.data.st_events import StDataPlugin
from empire.plugins.data.stocks import StockDataPlugin
from empire.plugins.data.suspensions import SuspensionDataPlugin
from empire.plugins.data.tdx_performance import PerformanceDataPlugin
from empire.plugins.data.ths_capital import CapitalPageDataPlugin
from empire.plugins.data.trade_calendar import CalendarDataPlugin
from empire.plugins.data.trading_rules import RuleDataPlugin
from empire.plugins.data.unlock_industries import UnlockIndustryDataPlugin
from empire.plugins.data.unlocks import UnlockDataPlugin
from empire.plugins.datasets.capital_actions import KINDS
from empire.plugins.datasets.financial_statements import KINDS as FINANCIAL_KINDS
from empire.plugins.infra.archive_confirmation import ArchiveConfirmationPlugin
from empire.plugins.infra.download_settings import DownloadSettingsPlugin
from empire.plugins.infra.http import HttpPlugin
from empire.plugins.infra.proxy_pool import ProxyPoolPlugin
from empire.plugins.ui.adjustment import AdjustmentUiPlugin
from empire.plugins.ui.capital_actions import CapitalUiPlugin
from empire.plugins.ui.collection import CollectionUiPlugin
from empire.plugins.ui.downloads import DownloadSettingsUiPlugin
from empire.plugins.ui.financial_statements import FinancialUiPlugin
from empire.plugins.ui.help import HelpUiPlugin
from empire.plugins.ui.holders import HolderUiPlugin
from empire.plugins.ui.index_prices import IndexPriceUiPlugin
from empire.plugins.ui.indices import IndexUiPlugin
from empire.plugins.ui.industries import IndustryUiPlugin
from empire.plugins.ui.kaipanla_products import KaipanlaProductUiPlugin
from empire.plugins.ui.listing_status import ListingStatusUiPlugin
from empire.plugins.ui.listings import ListingUiPlugin
from empire.plugins.ui.name_changes import NameUiPlugin
from empire.plugins.ui.news import NewsUiPlugin
from empire.plugins.ui.preparation import PreparationUiPlugin
from empire.plugins.ui.proxies import ProxyUiPlugin
from empire.plugins.ui.repurchases import RepurchaseUiPlugin
from empire.plugins.ui.st_events import StUiPlugin
from empire.plugins.ui.stocks import StockUiPlugin
from empire.plugins.ui.suspensions import SuspensionsUiPlugin
from empire.plugins.ui.system import SystemUiPlugin
from empire.plugins.ui.tdx_performance import PerformanceUiPlugin
from empire.plugins.ui.ths_capital import CapitalPageUiPlugin
from empire.plugins.ui.trade_calendar import CalendarUiPlugin
from empire.plugins.ui.trading_rules import RuleUiPlugin
from empire.plugins.ui.unlock_industries import UnlockIndustryUiPlugin
from empire.plugins.ui.unlocks import UnlockUiPlugin
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
    rate_groups.setdefault('eastmoney', {'domains': ['eastmoney.com'], 'min_interval_ms': 2000,
        'proxy_interval_ms': 2000, 'total_interval_ms': 2000, 'max_concurrency': 1, 'scaling_mode': 'fixed'})
    rate_groups.setdefault('bse', {'domains': ['bse.cn'], 'min_interval_ms': 2000})
    for group, domains in {"sse": ["sse.com.cn"], "szse": ["szse.cn"], "tax": ["chinatax.gov.cn"], "government": ["gov.cn"], "chinaclear": ["chinaclear.cn"], "chinagate": ["chinagate.cn"]}.items():
        rate_groups.setdefault(group, {"domains": domains, "min_interval_ms": 2000})
    plugins = [
        *(HolderDataPlugin(k, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for k in HOLDER_KINDS),
        HolderCollector(),
        CapitalPageDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})),
        CapitalPageCollector(), CapitalPageUiPlugin(),
        *(HolderUiPlugin(k) for k in HOLDER_KINDS),
        *(PerformanceDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in PERFORMANCE_KINDS),
        *(PerformanceCollector(kind) for kind in PERFORMANCE_KINDS),
        *(PerformanceUiPlugin(kind) for kind in PERFORMANCE_KINDS),
        UnlockIndustryDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})), UnlockIndustryCollector(), UnlockIndustryUiPlugin(),
        UnlockDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})), UnlockCollector(), UnlockUiPlugin(),
        RepurchaseDataPlugin(cfg['redis'].get('namespace', 'empire')), RepurchaseCollector(), RepurchaseUiPlugin(),
        RuleSources(),
        *(RuleDataPlugin(k, cfg["redis"].get("namespace", "empire"), cfg.get("archive", {})) for k in RULE_KINDS),
        *(RuleCollector(k) for k in RULE_KINDS),
        *(RuleUiPlugin(k) for k in RULE_KINDS),
        IndexPriceDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})),
        ThsIndexPriceCollector(), IndexPriceUiPlugin(),
        DatasetPlugin(), RedisPlugin(cfg["redis"]), MySQLPlugin(cfg["mysql"]),
        RecordsPlugin(secrets=tuple(
            cfg.get(section, {}).get("password", "") for section in ("redis", "mysql")
        )),
        ProxyPoolPlugin(), DownloadSettingsPlugin(), HttpPlugin(rate_groups, cfg.get("http", {})),
        ArchivePlugin(cfg["archive"]), IngestPlugin(cfg["ingest"]), ArchiveConfirmationPlugin(),
        StockDataPlugin(cfg["redis"].get("namespace", "empire")),
        ListingDataPlugin(cfg['redis'].get('namespace', 'empire')), ThsListingCollector(), ListingUiPlugin(),
        ListingStatusDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})),
        TdxListingStatusCollector(), ListingStatusUiPlugin(),
        IndustryDataPlugin(namespace=cfg['redis'].get('namespace', 'empire'),
                           archive_settings=cfg.get('archive', {})),
        ThsIndustryCollector(), IndustryUiPlugin(),
        IndexDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})), ThsIndexCollector(), IndexUiPlugin(),
        *(NameDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in NAME_KINDS),
        *(NameChangeCollector(kind) for kind in NAME_KINDS),
        *(NameUiPlugin(kind) for kind in NAME_KINDS),
        *(StDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in ST_KINDS),
        *(StEventCollector(kind) for kind in ST_KINDS),
        *(StUiPlugin(kind) for kind in ST_KINDS),
        *(KaipanlaProductDataPlugin(kind, namespace=cfg['redis'].get('namespace', 'empire')) for kind in PRODUCTS),
        *(KaipanlaProductCollector(kind) for kind in PRODUCTS),
        *(KaipanlaProductUiPlugin(kind) for kind in PRODUCTS),
        AdjustmentDataPlugin(cfg['redis'].get('namespace', 'empire')), AdjustmentUiPlugin(),
        SinaUniverseCollector(cfg.get("sina_universe", {})), ThsUniverseCollector(),
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
        CollectionControl([TaskContribution('tdx-unlock-industries', '大小非解禁行业（通达信）',
            'collector.tdx_unlock_industries', 'tdx', '完整可得月份行业汇总及估值基准日，无分页参数',
            category='股东数据', source_name='通达信', parallel_downloads=True, unit_name='个月',
            default_schedule=TaskDefaults('daily', description='每天北京时间18:00回查当前来源目录全部月份；保留已退出目录历史，可编辑。'),
            fresh_description='重建当前月份目录与估值基准日；已入队轮次先完成归档；保留旧月份。'), TaskContribution('tdx-unlocks', '大小非解禁个股与明细（通达信）',
            'collector.tdx_unlocks', 'tdx', '列表10000000；完整月份与对应共享股东明细，首次历史补齐',
            category='股东数据', source_name='通达信', parallel_downloads=True, unit_name='个月', default_enabled=False,
            default_schedule=TaskDefaults('daily', description='每天北京时间18:00核验月份列表并补明细；每轮轮换回查一个历史月；可编辑。'),
            fresh_description='重建声明月份范围并完整回查所有股东明细；已入队轮次先完成归档。'), TaskContribution(holder_project('top_holders'), '股东研究（同花顺）',
            'collector.ths_holders', 'ths', '一次HTML采集前十大股东、流通股东和债券持有人；历史保留，无公告日期',
            category='股东数据', source_name='同花顺', parallel_downloads=True, unit_name='只股票', default_enabled=False,
            default_schedule=TaskDefaults('daily', description='每天北京时间18:00核验当前报告窗口及修订；可编辑计划。'),
            fresh_description='重建当前股票池和页面报告窗口；保留历史；待归档阶段先确认原轮次。'),
            TaskContribution('ths-capital', '公司资本运作（同花顺）', 'collector.ths_capital', 'ths',
            '一次HTML完整采集融资、投资、交易、参股IPO及质押解冻，原币种与历史保留',
            category='公司行动', source_name='同花顺', parallel_downloads=True, unit_name='只股票', default_enabled=False,
            default_schedule=TaskDefaults('daily', daily_time='18:30', description='每天北京时间18:30完整核验页面历史和解除修订；启用后生效，可编辑。'),
            fresh_description='重建当前股票池和页面全部栏目；保留历史；待归档阶段先确认原轮次。'),
            *(TaskContribution(performance_project(kind), item[0] + '（通达信）',
            'collector.tdx_' + kind, 'tdx', '每页10000；完整来源单元、历史回查及结构化查询',
            category=item[3], source_name='通达信', parallel_downloads=True, unit_name='个完整响应',
            default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整回查来源单元历史；首次补来源可得范围，可编辑。'),
            fresh_description='下载阶段重新建立完整来源范围；待归档阶段先确认原轮次；保留所有已归档历史。')
            for kind, item in PERFORMANCE_KINDS.items()), TaskContribution('eastmoney-repurchases', '股票回购（东方财富）',
            'collector.eastmoney_repurchase', 'eastmoney', '唯一方案编号游标，全量核验历史及修订；不推断股份注销',
            category='公司行动', source_name='东方财富', unit_name='页',
            default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整核验方案与累计进展，发现历史修订；可编辑。'),
            fresh_description='从首方案重新核验完整来源；不删除历史；待归档阶段先确认原轮次，下载阶段可重新建立范围。'),*(TaskContribution(rule_project(k), title, 'collector.rules_' + k, 'tax' if k == 'stamp_duty' else 'chinagate' if k == 'transfer_fee' else 'sse',
            '官方生效条款及参数；支持范围和未核实项在数据准备独立显示',
            category='交易费用' if k in ('stamp_duty', 'transfer_fee') else '交易规则', source_name='官方规则',
            interval_seconds=259200, parallel_downloads=True, unit_name='组官方规则',
            default_schedule=TaskDefaults('interval', interval_seconds=259200, description='每次任务结束3天后复查官方文件及规则目录，可编辑计划。'),
            fresh_description='重新核验已审核官方文件；保留历史规则，已入队轮次先完成归档。') for k, title in RULE_KINDS.items()),
            TaskContribution('tdx-listing-status', '暂停恢复终止上市（通达信）',
            'collector.tdx_listing_status', 'tdx', '沪深A股三类事件；逐日核验，按月独立归档',
            category='证券基础', source_name='通达信', parallel_downloads=True, unit_name='个月', default_schedule=TaskDefaults('daily',
                description='每天北京时间18:00补缺并回查最近一个月；首次补历史，计划可编辑。'),
            fresh_description='从1990-12-19逐日重新核验至本轮启动日；保留已归档事件，先继续活跃轮次。'),
            TaskContribution('ths-index-prices', '同花顺指数历史日行情',
            'collector.ths_index_prices', 'ths', '逐年补齐来源可得历史；last更新近期；开高低收及量额',
            category='指数数据', source_name='同花顺', parallel_downloads=True, unit_name='个指数',
            default_schedule=TaskDefaults('daily', description='每天北京时间18:00补缺及更新近期日线；初次补历史，计划可编辑。'),
            fresh_description='回查来源全部年份，保留已有历史；未完成轮次先继续，不提供历史版本回放。'),
            *(TaskContribution(st_project(kind), item[0] + '（通达信）',
            'collector.tdx_st_' + kind, 'tdx', '全部来源历史单响应；日期、前后简称、原因及行业',
            category='交易状态', source_name='通达信', unit_name='次完整响应',
            default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整核验历史，发现新增及修订；计划可编辑。'),
            fresh_description='重新核验来源全部历史；已入队轮次先完成归档，不裁定每日ST状态。')
            for kind, item in ST_KINDS.items()),
            *(TaskContribution(name_project(kind), item[0] + '（通达信）',
            'collector.tdx_' + kind + '_renames', 'tdx', '一次完整历史响应；缺名及链断裂独立显示',
            category='证券基础', source_name='通达信', unit_name='次完整响应', default_schedule=TaskDefaults('daily',
                description='每天北京时间18:00核验全部历史，一次请求发现新增与历史修订；可编辑计划。'),
            fresh_description='核验来源全部更名历史；已入队轮次先完成归档，缺失名称保持未知。')
            for kind, item in NAME_KINDS.items()), *(TaskContribution(project(kind), '开盘啦' + item.title,
            'collector.kaipanla_' + kind, 'kaipanla', item.note,
            category='高频行情', source_name='开盘啦', interval_seconds=86400, unit_name='股票日',
            parallel_downloads=True, default_enabled=False,
            default_schedule=HISTORICAL_DAY_DEFAULTS,
            fresh_description='从 2021 年起逐证券日重新核验本项，保留已归档历史；普通采集补缺，每周回看最近五个交易日。')
            for kind, item in PRODUCTS.items()),
            TaskContribution('ths-listings', '股票上市与发行资料（同花顺）',
            'collector.ths_listings', 'ths', '逐证券补缺，每七天回查当前股票池；保留已存退市证券资料',
            category='证券基础', source_name='同花顺', parallel_downloads=True, unit_name='只股票', default_schedule=TaskDefaults('daily',
                description='每天北京时间18:00补新增和缺失；每七天全池回查独立修订；计划可编辑。'),
            fresh_description='逐只重查当前股票池的上市及发行资料；保留已有记录及已入队消息。'),
            TaskContribution('ths-industries', '同花顺当前行业',
            'collector.ths_industries', 'ths', '最新行业名单与全部成分股票 · 不保存变化历史',
            category='证券基础', source_name='同花顺', interval_seconds=86400, parallel_downloads=True, unit_name='个行业',
            fresh_description='完整刷新当前行业和成分；已入队整轮先完成归档，不保留历史变化。'),
            TaskContribution('ths-indices', '同花顺当前指数及成分',
            'collector.ths_indices', 'ths', '完整指数目录及当前成分；来源暂无单独呈现，不保存历史调样',
            category='指数数据', source_name='同花顺', parallel_downloads=True, unit_name='个指数',
            default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整刷新目录和当前成员；计划可编辑。'),
            fresh_description='完整刷新当前目录和成分；未完成轮次先续跑并归档，不保存历史调样。'),
            *(TaskContribution('ths-' + kind, item[0] + '（同花顺）',
            'collector.ths_' + kind, 'ths', '逐证券完整历史 · 来源舍入金额 · 无公告日期',
            category='基本面', source_name='同花顺', interval_seconds=86400, parallel_downloads=True, unit_name='只股票',
            fresh_description='从当前股票池首个证券重查全部历史；保留已归档报表。')
            for kind, item in FINANCIAL_KINDS.items()),*(TaskContribution(item[2], item[0] + '（通达信）',
            'collector.tdx_' + kind, 'tdx', '全部可得历史核验 · 单证券完整归档',
            category='增发送配', source_name='通达信', parallel_downloads=kind != 'rights_issues', unit_name='只股票',
            fresh_description='从当前来源完整范围重新核验，保留已归档历史；普通采集优先续跑已入队断点。')
            for kind, item in KINDS.items()), TaskContribution('ths-stocks', '同花顺 A 股股票列表',
            'collector.ths_universe', 'ths', '沪深北完整单页目录 · 一次HTTP获取代码与名称',
            category='基础数据', source_name='同花顺', unit_name='只股票', default_schedule=TaskDefaults('daily',
                description='每天北京时间18:00完整核验一次当前目录；可编辑执行计划。')),
            TaskContribution("sina-stocks", "新浪 A 股股票列表",
            "collector.sina_universe", "sina", "沪深北全量股票 · 代码 / 名称 / 统一代码 / 市场",
            category="基础数据", source_name="新浪财经", parallel_downloads=True, unit_name='只股票'),
            TaskContribution("sina-news", "新浪 7×24 小时全球实时财经新闻直播",
            "collector.sina_news", "sina", "最新窗口刷新与增量补采 · 正文 / 时间 / 分类 / 重点新闻",
            interval_seconds=60, category="资讯", source_name="新浪财经", unit_name='条新闻',
            fresh_description="重新扫描最新窗口并建立增量基线，已有新闻保留；请先检查尚未处理的缺口。"),
            TaskContribution("cninfo-calendar", "大 A 交易日期（巨潮资讯）",
            "collector.cninfo_calendar", "cninfo", "首次补齐历史 · 后续维护本月至下一年 12 月 · 交易日 / 休市日",
            interval_seconds=86400, category="基础数据", source_name="巨潮资讯", parallel_downloads=True, unit_name='个月',
            fresh_description="从 1990-12 起重新核验全部月份至下一年 12 月；正常维护请用立即采集。"),
            TaskContribution("tdx-suspensions", "沪深 A 股历史停复牌（通达信）",
            "collector.tdx_suspensions", "tdx", "2004-12-27 起逐自然日完整检查 · 停牌 / 复牌 / 全天或临停",
            interval_seconds=86400, category="交易可实现性", source_name="通达信", parallel_downloads=True, unit_name='个月',
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
