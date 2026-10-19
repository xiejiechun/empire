"""Existing declarations at their unchanged ordinal positions."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.index_prices import dataset as index_prices
from empire.features.index_prices.collector import ThsIndexPriceCollector
from empire.features.index_prices.query import IndexPriceDataPlugin
from empire.features.index_prices.ui import IndexPriceUiPlugin


def bundle(cfg):
    return FeatureBundle('index_prices', plugins=(
        OrderedContribution(6000, IndexPriceDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {}))),
        OrderedContribution(6100, ThsIndexPriceCollector()),
        OrderedContribution(6200, IndexPriceUiPlugin()),
    ), tasks=(
        OrderedContribution(2000, TaskContribution('ths-index-prices', '同花顺指数历史日行情',
                    'collector.ths_index_prices', 'ths', '逐年补齐来源可得历史；last更新近期；开高低收及量额',
                    category='指数数据', source_name='同花顺', parallel_downloads=True, unit_name='个指数',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00补缺及更新近期日线；初次补历史，计划可编辑。'),
                    fresh_description='回查来源全部年份，保留已有历史；未完成轮次先继续，不提供历史版本回放。')),
    ), datasets=(
        OrderedContribution(1900, DatasetContribution(index_prices, 'incremental', {index_prices.JOB: index_prices.PROJECT})),
    ))
