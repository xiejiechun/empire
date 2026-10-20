"""Listing status keeps original contribution identities and slots."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.listing_status import dataset as listing_status
from empire.features.listing_status.collector import TdxListingStatusCollector
from empire.features.listing_status.contract import JOB as STATUS_JOB
from empire.features.listing_status.contract import PROJECT as STATUS_PROJECT
from empire.features.listing_status.query import ListingStatusDataPlugin
from empire.features.listing_status.ui import ListingStatusUiPlugin


def bundle(cfg):
    return FeatureBundle('listing_status', plugins=(
        OrderedContribution(7700, ListingStatusDataPlugin(cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {}))),
        OrderedContribution(7800, TdxListingStatusCollector()),
        OrderedContribution(7900, ListingStatusUiPlugin()),
    ), tasks=(
        OrderedContribution(1900, TaskContribution('tdx-listing-status', '暂停恢复终止上市（通达信）',
                    'collector.tdx_listing_status', 'tdx', '沪深A股三类事件；逐日核验，按月独立归档',
                    category='证券基础', source_name='通达信', parallel_downloads=True, unit_name='个月', default_schedule=TaskDefaults('daily',
                        description='每天北京时间18:00补缺并回查最近一个月；首次补历史，计划可编辑。'),
                    fresh_description='从1990-12-19逐日重新核验至本轮启动日；保留已归档事件，先继续活跃轮次。')),
    ), datasets=(
        OrderedContribution(2200, DatasetContribution(listing_status, 'incremental', {STATUS_JOB: STATUS_PROJECT})),
    ))
