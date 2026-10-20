"""Original identities and ordered contributions owned by this business."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.unlock_industries.collector import UnlockIndustryCollector
from empire.features.unlock_industries.dataset import UnlockIndustryDataset
from empire.features.unlock_industries.query import UnlockIndustryDataPlugin
from empire.features.unlock_industries.ui import UnlockIndustryUiPlugin


def bundle(cfg):
    return FeatureBundle('unlock_industries', plugins=(
        OrderedContribution(2900, UnlockIndustryDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {}))),
        OrderedContribution(3000, UnlockIndustryCollector()),
        OrderedContribution(3100, UnlockIndustryUiPlugin()),
    ), tasks=(
        OrderedContribution(100, TaskContribution('tdx-unlock-industries', '大小非解禁行业（通达信）',
                    'collector.tdx_unlock_industries', 'tdx', '完整可得月份行业汇总及估值基准日，无分页参数',
                    category='股东数据', source_name='通达信', parallel_downloads=True, unit_name='个月',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00回查当前来源目录全部月份；保留已退出目录历史，可编辑。'),
                    fresh_description='重建当前月份目录与估值基准日；已入队轮次先完成归档；保留旧月份。')),
    ), datasets=(
        OrderedContribution(200, DatasetContribution(UnlockIndustryDataset(), 'incremental', {UnlockIndustryDataset.JOB: UnlockIndustryDataset.PROJECT})),
    ))
