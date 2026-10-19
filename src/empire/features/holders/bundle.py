"""Original holder declarations at their stable, noncontiguous positions."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution, positioned
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.holders.collector import HolderCollector
from empire.features.holders.contract import KINDS as HOLDER_KINDS
from empire.features.holders.contract import project as holder_project
from empire.features.holders.dataset import HolderDataset
from empire.features.holders.query import HolderDataPlugin
from empire.features.holders.ui import HolderUiPlugin


def bundle(cfg):
    return FeatureBundle('holders', plugins=(
        *positioned((100, 200, 300), (HolderDataPlugin(k, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for k in HOLDER_KINDS)),
        OrderedContribution(400, HolderCollector()),
        *positioned((800, 900, 1000), (HolderUiPlugin(k) for k in HOLDER_KINDS)),
    ), tasks=(
        OrderedContribution(300, TaskContribution(holder_project('top_holders'), '股东研究（同花顺）',
                    'collector.ths_holders', 'ths', '一次HTML采集前十大股东、流通股东和债券持有人；历史保留，无公告日期',
                    category='股东数据', source_name='同花顺', parallel_downloads=True, unit_name='只股票', default_enabled=False,
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00核验当前报告窗口及修订；可编辑计划。'),
                    fresh_description='重建当前股票池和页面报告窗口；保留历史；待归档阶段先确认原轮次。')),
    ), datasets=(
        OrderedContribution(400, DatasetContribution(HolderDataset(), 'incremental',
                        {HolderDataset().JOB: HolderDataset().PROJECT}, schema_version=5)),
    ))
