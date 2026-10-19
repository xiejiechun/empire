"""Existing declarations at their unchanged ordinal positions."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.indices import dataset as indices
from empire.features.indices.collector import ThsIndexCollector
from empire.features.indices.contract import JOB as INDEX_JOB
from empire.features.indices.contract import PROJECT as INDEX_PROJECT
from empire.features.indices.query import IndexDataPlugin
from empire.features.indices.ui import IndexUiPlugin


def bundle(cfg):
    return FeatureBundle('indices', plugins=(
        OrderedContribution(8300, IndexDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {}))),
        OrderedContribution(8400, ThsIndexCollector()),
        OrderedContribution(8500, IndexUiPlugin()),
    ), tasks=(
        OrderedContribution(3400, TaskContribution('ths-indices', '同花顺当前指数及成分',
                    'collector.ths_indices', 'ths', '完整指数目录及当前成分；来源暂无单独呈现，不保存历史调样',
                    category='指数数据', source_name='同花顺', parallel_downloads=True, unit_name='个指数',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整刷新目录和当前成员；计划可编辑。'),
                    fresh_description='完整刷新当前目录和成分；未完成轮次先续跑并归档，不保存历史调样。')),
    ), datasets=(
        OrderedContribution(2100, DatasetContribution(indices, 'incremental', {INDEX_JOB: INDEX_PROJECT})),
    ))
