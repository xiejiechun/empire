"""Original repurchase identities and contribution slots, owned once."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.repurchases import dataset as repurchases
from empire.features.repurchases.collector import RepurchaseCollector
from empire.features.repurchases.query import RepurchaseDataPlugin
from empire.features.repurchases.ui import RepurchaseUiPlugin


def bundle(cfg):
    return FeatureBundle("repurchases", plugins=(
        OrderedContribution(3500, RepurchaseDataPlugin(cfg['redis'].get('namespace', 'empire'))),
        OrderedContribution(3600, RepurchaseCollector()),
        OrderedContribution(3700, RepurchaseUiPlugin()),
    ), tasks=(
        OrderedContribution(1100, TaskContribution('eastmoney-repurchases', '股票回购',
                    'collector.eastmoney_repurchase', 'eastmoney', '近期更新增量；每三天完整核验历史及修订；不推断股份注销',
                    category='公司行动', source_name='东方财富', unit_name='页',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00核验近期更新；每三天完整核验历史，计划可编辑。'),
                    fresh_description='从首方案重新核验完整来源；不删除历史；待归档阶段先确认原轮次，下载阶段可重新建立范围。')),
    ), datasets=(
        OrderedContribution(1100, DatasetContribution(repurchases, 'incremental', {'eastmoney-repurchases-v1': 'eastmoney-repurchases'})),
    ))
