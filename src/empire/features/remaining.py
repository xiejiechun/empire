"""Single declaration owner for businesses awaiting their own package; retired by batch E."""
from empire.contracts.bundle import (
    FeatureBundle,
    OrderedContribution,
    positioned,
)
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.contracts.trading_rules import KINDS as RULE_KINDS
from empire.contracts.trading_rules import project as rule_project
from empire.plugins.collectors.rule_sources import RuleSources
from empire.plugins.collectors.trading_rules import RuleCollector
from empire.plugins.data.trading_rules import RuleDataPlugin
from empire.plugins.datasets.trading_rules import RuleDataset
from empire.plugins.ui.trading_rules import RuleUiPlugin


def bundle(cfg):
    """Unmigrated business declarations, removed here as each package takes ownership."""
    return FeatureBundle('remaining', plugins=(
        OrderedContribution(3800, RuleSources()),
        *positioned((3900, 4000, 4100, 4200, 4300, 4400, 4500), (RuleDataPlugin(k, cfg["redis"].get("namespace", "empire"), cfg.get("archive", {})) for k in RULE_KINDS)),
        *positioned((4600, 4700, 4800, 4900, 5000, 5100, 5200), (RuleCollector(k) for k in RULE_KINDS)),
        *positioned((5300, 5400, 5500, 5600, 5700, 5800, 5900), (RuleUiPlugin(k) for k in RULE_KINDS)),
    ), tasks=(
        *positioned((1200, 1300, 1400, 1500, 1600, 1700, 1800), (TaskContribution(rule_project(k), title, 'collector.rules_' + k, 'tax' if k == 'stamp_duty' else 'chinagate' if k == 'transfer_fee' else 'sse',
                    '官方生效条款及参数；支持范围和未核实项在数据准备独立显示',
                    category='交易费用' if k in ('stamp_duty', 'transfer_fee') else '交易规则', source_name='官方规则',
                    interval_seconds=259200, parallel_downloads=True, unit_name='组官方规则',
                    default_schedule=TaskDefaults('interval', interval_seconds=259200, description='每次任务结束3天后复查官方文件及规则目录，可编辑计划。'),
                    fresh_description='重新核验已审核官方文件；保留历史规则，已入队轮次先完成归档。') for k, title in RULE_KINDS.items())),
    ), datasets=(
        *positioned((1200, 1300, 1400, 1500, 1600, 1700, 1800), (DatasetContribution(RuleDataset(kind), 'incremental', {RuleDataset(kind).JOB: RuleDataset(kind).PROJECT}) for kind in RULE_KINDS)),
    ))
