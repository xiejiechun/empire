"""Single declaration owner for businesses awaiting their own package; retired by batch E."""
from empire.contracts.bundle import (
    FeatureBundle,
    OrderedContribution,
    positioned,
)
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.contracts.tdx_performance import UNIT_KINDS as PERFORMANCE_KINDS
from empire.contracts.tdx_performance import project as performance_project
from empire.contracts.trading_rules import KINDS as RULE_KINDS
from empire.contracts.trading_rules import project as rule_project
from empire.plugins.collectors.eastmoney_repurchase import RepurchaseCollector
from empire.plugins.collectors.rule_sources import RuleSources
from empire.plugins.collectors.tdx_performance import PerformanceCollector
from empire.plugins.collectors.trading_rules import RuleCollector
from empire.plugins.data.repurchases import RepurchaseDataPlugin
from empire.plugins.data.tdx_performance import PerformanceDataPlugin
from empire.plugins.data.trading_rules import RuleDataPlugin
from empire.plugins.datasets import repurchases
from empire.plugins.datasets.tdx_performance import PerformanceDataset
from empire.plugins.datasets.trading_rules import RuleDataset
from empire.plugins.ui.repurchases import RepurchaseUiPlugin
from empire.plugins.ui.tdx_performance import PerformanceUiPlugin
from empire.plugins.ui.trading_rules import RuleUiPlugin


def bundle(cfg):
    """Unmigrated business declarations, removed here as each package takes ownership."""
    return FeatureBundle('remaining', plugins=(
        *positioned((1100, 1200, 1300, 1400, 1500, 1600), (PerformanceDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in PERFORMANCE_KINDS)),
        *positioned((1700, 1800, 1900, 2000, 2100, 2200), (PerformanceCollector(kind) for kind in PERFORMANCE_KINDS)),
        *positioned((2300, 2400, 2500, 2600, 2700, 2800), (PerformanceUiPlugin(kind) for kind in PERFORMANCE_KINDS)),
        OrderedContribution(3500, RepurchaseDataPlugin(cfg['redis'].get('namespace', 'empire'))),
        OrderedContribution(3600, RepurchaseCollector()),
        OrderedContribution(3700, RepurchaseUiPlugin()),
        OrderedContribution(3800, RuleSources()),
        *positioned((3900, 4000, 4100, 4200, 4300, 4400, 4500), (RuleDataPlugin(k, cfg["redis"].get("namespace", "empire"), cfg.get("archive", {})) for k in RULE_KINDS)),
        *positioned((4600, 4700, 4800, 4900, 5000, 5100, 5200), (RuleCollector(k) for k in RULE_KINDS)),
        *positioned((5300, 5400, 5500, 5600, 5700, 5800, 5900), (RuleUiPlugin(k) for k in RULE_KINDS)),
    ), tasks=(
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
    ), datasets=(
        *positioned((500, 600, 700, 800, 900, 1000), (DatasetContribution(PerformanceDataset(kind), 'incremental',
                        {PerformanceDataset(kind).JOB: PerformanceDataset(kind).PROJECT}) for kind in PERFORMANCE_KINDS)),
        OrderedContribution(1100, DatasetContribution(repurchases, 'incremental', {'eastmoney-repurchases-v1': 'eastmoney-repurchases'})),
        *positioned((1200, 1300, 1400, 1500, 1600, 1700, 1800), (DatasetContribution(RuleDataset(kind), 'incremental', {RuleDataset(kind).JOB: RuleDataset(kind).PROJECT}) for kind in RULE_KINDS)),
    ))
