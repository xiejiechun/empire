"""Original identities and ordered contributions owned by this business."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.unlocks.collector import UnlockCollector
from empire.features.unlocks.dataset import UnlockDataset
from empire.features.unlocks.query import UnlockDataPlugin
from empire.features.unlocks.ui import UnlockUiPlugin


def bundle(cfg):
    return FeatureBundle('unlocks', plugins=(
        OrderedContribution(3200, UnlockDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {}))),
        OrderedContribution(3300, UnlockCollector()),
        OrderedContribution(3400, UnlockUiPlugin()),
    ), tasks=(
        OrderedContribution(200, TaskContribution('tdx-unlocks', '大小非解禁个股与明细（通达信）',
                    'collector.tdx_unlocks', 'tdx', '列表10000000；完整月份与对应共享股东明细，首次历史补齐',
                    category='股东数据', source_name='通达信', parallel_downloads=True, unit_name='个月', default_enabled=False,
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00核验月份列表并补明细；每轮轮换回查一个历史月；可编辑。'),
                    fresh_description='重建声明月份范围并完整回查所有股东明细；已入队轮次先完成归档。')),
    ), datasets=(
        OrderedContribution(300, DatasetContribution(UnlockDataset(), 'incremental', {UnlockDataset.JOB: UnlockDataset.PROJECT})),
    ))
