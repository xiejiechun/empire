"""Existing declarations at their unchanged ordinal positions."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution
from empire.features.industries import dataset as industries
from empire.features.industries.collector import ThsIndustryCollector
from empire.features.industries.query import IndustryDataPlugin
from empire.features.industries.ui import IndustryUiPlugin


def bundle(cfg):
    return FeatureBundle('industries', plugins=(
        OrderedContribution(8000, IndustryDataPlugin(namespace=cfg['redis'].get('namespace', 'empire'),
                                   archive_settings=cfg.get('archive', {}))),
        OrderedContribution(8100, ThsIndustryCollector()),
        OrderedContribution(8200, IndustryUiPlugin()),
    ), tasks=(
        OrderedContribution(3300, TaskContribution('ths-industries', '同花顺当前行业',
                    'collector.ths_industries', 'ths', '最新行业名单与全部成分股票 · 不保存变化历史',
                    category='证券基础', source_name='同花顺', interval_seconds=86400, parallel_downloads=True, unit_name='个行业',
                    fresh_description='完整刷新当前行业和成分；已入队整轮先完成归档，不保留历史变化。')),
    ), datasets=(
        OrderedContribution(3500, DatasetContribution(industries, 'incremental', {industries.JOB: industries.PROJECT})),
    ))
