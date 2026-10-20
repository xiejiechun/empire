"""Single declaration owner for businesses awaiting their own package; retired by batch E."""
from empire.contracts.bundle import (
    FeatureBundle,
    MaintenancePublisher,
    OrderedContribution,
    positioned,
)
from empire.contracts.dataset import DatasetContribution
from empire.contracts.listing_status import JOB as STATUS_JOB
from empire.contracts.listing_status import PROJECT as STATUS_PROJECT
from empire.contracts.listings import JOB as LISTING_JOB
from empire.contracts.listings import PROJECT as LISTING_PROJECT
from empire.contracts.name_changes import KINDS as NAME_KINDS
from empire.contracts.name_changes import SCHEMA_VERSION as NAME_SCHEMA_VERSION
from empire.contracts.name_changes import project as name_project
from empire.contracts.st_events import KINDS as ST_KINDS
from empire.contracts.st_events import SCHEMA_VERSION as ST_SCHEMA_VERSION
from empire.contracts.st_events import project as st_project
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.contracts.tdx_performance import UNIT_KINDS as PERFORMANCE_KINDS
from empire.contracts.tdx_performance import project as performance_project
from empire.contracts.trading_rules import KINDS as RULE_KINDS
from empire.contracts.trading_rules import project as rule_project
from empire.plugins.collectors.eastmoney_repurchase import RepurchaseCollector
from empire.plugins.collectors.rule_sources import RuleSources
from empire.plugins.collectors.tdx_listing_status import TdxListingStatusCollector
from empire.plugins.collectors.tdx_name_changes import NameChangeCollector
from empire.plugins.collectors.tdx_performance import PerformanceCollector
from empire.plugins.collectors.tdx_st_events import StEventCollector
from empire.plugins.collectors.tdx_unlock_industries import UnlockIndustryCollector
from empire.plugins.collectors.tdx_unlocks import UnlockCollector
from empire.plugins.collectors.ths_listings import ThsListingCollector
from empire.plugins.collectors.trading_rules import RuleCollector
from empire.plugins.data.listing_status import ListingStatusDataPlugin
from empire.plugins.data.listings import ListingDataPlugin
from empire.plugins.data.name_changes import NameDataPlugin
from empire.plugins.data.repurchases import RepurchaseDataPlugin
from empire.plugins.data.st_events import StDataPlugin
from empire.plugins.data.tdx_performance import PerformanceDataPlugin
from empire.plugins.data.trading_rules import RuleDataPlugin
from empire.plugins.data.unlock_industries import UnlockIndustryDataPlugin
from empire.plugins.data.unlocks import UnlockDataPlugin
from empire.plugins.datasets import listing_status, listings, repurchases, security_aliases
from empire.plugins.datasets.name_changes import NameDataset
from empire.plugins.datasets.st_events import StDataset
from empire.plugins.datasets.tdx_performance import PerformanceDataset
from empire.plugins.datasets.trading_rules import RuleDataset
from empire.plugins.datasets.unlock_industries import UnlockIndustryDataset
from empire.plugins.datasets.unlocks import UnlockDataset
from empire.plugins.ui.listing_status import ListingStatusUiPlugin
from empire.plugins.ui.listings import ListingUiPlugin
from empire.plugins.ui.name_changes import NameUiPlugin
from empire.plugins.ui.repurchases import RepurchaseUiPlugin
from empire.plugins.ui.st_events import StUiPlugin
from empire.plugins.ui.tdx_performance import PerformanceUiPlugin
from empire.plugins.ui.trading_rules import RuleUiPlugin
from empire.plugins.ui.unlock_industries import UnlockIndustryUiPlugin
from empire.plugins.ui.unlocks import UnlockUiPlugin


def bundle(cfg):
    """Unmigrated business declarations, removed here as each package takes ownership."""
    return FeatureBundle('remaining', plugins=(
        *positioned((1100, 1200, 1300, 1400, 1500, 1600), (PerformanceDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in PERFORMANCE_KINDS)),
        *positioned((1700, 1800, 1900, 2000, 2100, 2200), (PerformanceCollector(kind) for kind in PERFORMANCE_KINDS)),
        *positioned((2300, 2400, 2500, 2600, 2700, 2800), (PerformanceUiPlugin(kind) for kind in PERFORMANCE_KINDS)),
        OrderedContribution(2900, UnlockIndustryDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {}))),
        OrderedContribution(3000, UnlockIndustryCollector()),
        OrderedContribution(3100, UnlockIndustryUiPlugin()),
        OrderedContribution(3200, UnlockDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {}))),
        OrderedContribution(3300, UnlockCollector()),
        OrderedContribution(3400, UnlockUiPlugin()),
        OrderedContribution(3500, RepurchaseDataPlugin(cfg['redis'].get('namespace', 'empire'))),
        OrderedContribution(3600, RepurchaseCollector()),
        OrderedContribution(3700, RepurchaseUiPlugin()),
        OrderedContribution(3800, RuleSources()),
        *positioned((3900, 4000, 4100, 4200, 4300, 4400, 4500), (RuleDataPlugin(k, cfg["redis"].get("namespace", "empire"), cfg.get("archive", {})) for k in RULE_KINDS)),
        *positioned((4600, 4700, 4800, 4900, 5000, 5100, 5200), (RuleCollector(k) for k in RULE_KINDS)),
        *positioned((5300, 5400, 5500, 5600, 5700, 5800, 5900), (RuleUiPlugin(k) for k in RULE_KINDS)),
        OrderedContribution(7400, ListingDataPlugin(cfg['redis'].get('namespace', 'empire'))),
        OrderedContribution(7500, ThsListingCollector()),
        OrderedContribution(7600, ListingUiPlugin()),
        OrderedContribution(7700, ListingStatusDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {}))),
        OrderedContribution(7800, TdxListingStatusCollector()),
        OrderedContribution(7900, ListingStatusUiPlugin()),
        *positioned((8600, 8700), (NameDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in NAME_KINDS)),
        *positioned((8800, 8900), (NameChangeCollector(kind) for kind in NAME_KINDS)),
        *positioned((9000, 9100), (NameUiPlugin(kind) for kind in NAME_KINDS)),
        *positioned((9200, 9300), (StDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in ST_KINDS)),
        *positioned((9400, 9500), (StEventCollector(kind) for kind in ST_KINDS)),
        *positioned((9600, 9700), (StUiPlugin(kind) for kind in ST_KINDS)),
    ), tasks=(
        OrderedContribution(100, TaskContribution('tdx-unlock-industries', '大小非解禁行业（通达信）',
                    'collector.tdx_unlock_industries', 'tdx', '完整可得月份行业汇总及估值基准日，无分页参数',
                    category='股东数据', source_name='通达信', parallel_downloads=True, unit_name='个月',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00回查当前来源目录全部月份；保留已退出目录历史，可编辑。'),
                    fresh_description='重建当前月份目录与估值基准日；已入队轮次先完成归档；保留旧月份。')),
        OrderedContribution(200, TaskContribution('tdx-unlocks', '大小非解禁个股与明细（通达信）',
                    'collector.tdx_unlocks', 'tdx', '列表10000000；完整月份与对应共享股东明细，首次历史补齐',
                    category='股东数据', source_name='通达信', parallel_downloads=True, unit_name='个月', default_enabled=False,
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00核验月份列表并补明细；每轮轮换回查一个历史月；可编辑。'),
                    fresh_description='重建声明月份范围并完整回查所有股东明细；已入队轮次先完成归档。')),
        *positioned((500, 600, 700, 800, 900, 1000), (TaskContribution(performance_project(kind), item[0] + '（通达信）',
                    'collector.tdx_' + kind, 'tdx', '每页10000；完整来源单元、历史回查及结构化查询',
                    category=item[3], source_name='通达信', parallel_downloads=True, unit_name='个完整响应',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整回查来源单元历史；首次补来源可得范围，可编辑。'),
                    fresh_description='下载阶段重新建立完整来源范围；待归档阶段先确认原轮次；保留所有已归档历史。')
                    for kind, item in PERFORMANCE_KINDS.items())),
        OrderedContribution(1100, TaskContribution('eastmoney-repurchases', '股票回购（东方财富）',
                    'collector.eastmoney_repurchase', 'eastmoney', '唯一方案编号游标，全量核验历史及修订；不推断股份注销',
                    category='公司行动', source_name='东方财富', unit_name='页',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整核验方案与累计进展，发现历史修订；可编辑。'),
                    fresh_description='从首方案重新核验完整来源；不删除历史；待归档阶段先确认原轮次，下载阶段可重新建立范围。')),
        *positioned((1200, 1300, 1400, 1500, 1600, 1700, 1800), (TaskContribution(rule_project(k), title, 'collector.rules_' + k, 'tax' if k == 'stamp_duty' else 'chinagate' if k == 'transfer_fee' else 'sse',
                    '官方生效条款及参数；支持范围和未核实项在数据准备独立显示',
                    category='交易费用' if k in ('stamp_duty', 'transfer_fee') else '交易规则', source_name='官方规则',
                    interval_seconds=259200, parallel_downloads=True, unit_name='组官方规则',
                    default_schedule=TaskDefaults('interval', interval_seconds=259200, description='每次任务结束3天后复查官方文件及规则目录，可编辑计划。'),
                    fresh_description='重新核验已审核官方文件；保留历史规则，已入队轮次先完成归档。') for k, title in RULE_KINDS.items())),
        OrderedContribution(1900, TaskContribution('tdx-listing-status', '暂停恢复终止上市（通达信）',
                    'collector.tdx_listing_status', 'tdx', '沪深A股三类事件；逐日核验，按月独立归档',
                    category='证券基础', source_name='通达信', parallel_downloads=True, unit_name='个月', default_schedule=TaskDefaults('daily',
                        description='每天北京时间18:00补缺并回查最近一个月；首次补历史，计划可编辑。'),
                    fresh_description='从1990-12-19逐日重新核验至本轮启动日；保留已归档事件，先继续活跃轮次。')),
        *positioned((2100, 2200), (TaskContribution(st_project(kind), item[0] + '（通达信）',
                    'collector.tdx_st_' + kind, 'tdx', '全部来源历史单响应；日期、前后简称、原因及行业',
                    category='交易状态', source_name='通达信', unit_name='次完整响应',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整核验历史，发现新增及修订；计划可编辑。'),
                    fresh_description='重新核验来源全部历史；已入队轮次先完成归档，不裁定每日ST状态。')
                    for kind, item in ST_KINDS.items())),
        *positioned((2300, 2400), (TaskContribution(name_project(kind), item[0] + '（通达信）',
                    'collector.tdx_' + kind + '_renames', 'tdx', '一次完整历史响应；缺名及链断裂独立显示',
                    category='证券基础', source_name='通达信', unit_name='次完整响应', default_schedule=TaskDefaults('daily',
                        description='每天北京时间18:00核验全部历史，一次请求发现新增与历史修订；可编辑计划。'),
                    fresh_description='核验来源全部更名历史；已入队轮次先完成归档，缺失名称保持未知。')
                    for kind, item in NAME_KINDS.items())),
        OrderedContribution(3200, TaskContribution('ths-listings', '股票上市与发行资料（同花顺）',
                    'collector.ths_listings', 'ths', '逐证券补缺，每七天回查当前股票池；保留已存退市证券资料',
                    category='证券基础', source_name='同花顺', parallel_downloads=True, unit_name='只股票', default_schedule=TaskDefaults('daily',
                        description='每天北京时间18:00补新增和缺失；每七天全池回查独立修订；计划可编辑。'),
                    fresh_description='逐只重查当前股票池的上市及发行资料；保留已有记录及已入队消息。')),
    ), datasets=(
        OrderedContribution(200, DatasetContribution(UnlockIndustryDataset(), 'incremental', {UnlockIndustryDataset.JOB: UnlockIndustryDataset.PROJECT})),
        OrderedContribution(300, DatasetContribution(UnlockDataset(), 'incremental', {UnlockDataset.JOB: UnlockDataset.PROJECT})),
        *positioned((500, 600, 700, 800, 900, 1000), (DatasetContribution(PerformanceDataset(kind), 'incremental',
                        {PerformanceDataset(kind).JOB: PerformanceDataset(kind).PROJECT}) for kind in PERFORMANCE_KINDS)),
        OrderedContribution(1100, DatasetContribution(repurchases, 'incremental', {'eastmoney-repurchases-v1': 'eastmoney-repurchases'})),
        *positioned((1200, 1300, 1400, 1500, 1600, 1700, 1800), (DatasetContribution(RuleDataset(kind), 'incremental', {RuleDataset(kind).JOB: RuleDataset(kind).PROJECT}) for kind in RULE_KINDS)),
        OrderedContribution(2000, DatasetContribution(security_aliases, 'incremental', {security_aliases.JOB: security_aliases.PROJECT})),
        OrderedContribution(2200, DatasetContribution(listing_status, 'incremental', {STATUS_JOB: STATUS_PROJECT})),
        OrderedContribution(2300, DatasetContribution(listings, 'incremental', {LISTING_JOB: LISTING_PROJECT})),
        *positioned((2400, 2500), (DatasetContribution(StDataset(kind), 'incremental',
                        {StDataset(kind).JOB: StDataset(kind).PROJECT}, schema_version=ST_SCHEMA_VERSION) for kind in ST_KINDS)),
        *positioned((2600, 2700), (DatasetContribution(NameDataset(kind), 'incremental',
                        {NameDataset(kind).JOB: NameDataset(kind).PROJECT}, schema_version=NAME_SCHEMA_VERSION) for kind in NAME_KINDS)),
    ), maintenance_publishers=(MaintenancePublisher(
        security_aliases.PROJECT, security_aliases.JOB, 'scripts/import_bse_code_mapping.py'),))
