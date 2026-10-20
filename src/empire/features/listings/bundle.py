"""Listing declarations preserving all original identity and order slots."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.listings import dataset as listings
from empire.features.listings.collector import ThsListingCollector
from empire.features.listings.contract import JOB as LISTING_JOB
from empire.features.listings.contract import PROJECT as LISTING_PROJECT
from empire.features.listings.query import ListingDataPlugin
from empire.features.listings.ui import ListingUiPlugin


def bundle(cfg):
    return FeatureBundle('listings', plugins=(
        OrderedContribution(7400, ListingDataPlugin(cfg['redis'].get('namespace', 'empire'))),
        OrderedContribution(7500, ThsListingCollector()),
        OrderedContribution(7600, ListingUiPlugin()),
    ), tasks=(
        OrderedContribution(3200, TaskContribution('ths-listings', '股票上市与发行资料（同花顺）',
                    'collector.ths_listings', 'ths', '逐证券补缺，每七天回查当前股票池；保留已存退市证券资料',
                    category='证券基础', source_name='同花顺', parallel_downloads=True, unit_name='只股票', default_schedule=TaskDefaults('daily',
                        description='每天北京时间18:00补新增和缺失；每七天全池回查独立修订；计划可编辑。'),
                    fresh_description='逐只重查当前股票池的上市及发行资料；保留已有记录及已入队消息。')),
    ), datasets=(
        OrderedContribution(2300, DatasetContribution(listings, 'incremental', {LISTING_JOB: LISTING_PROJECT})),
    ))
