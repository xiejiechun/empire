"""Explicit native PC history feature declarations."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.yuanhang import dataset
from empire.features.yuanhang.collector import YuanhangCollector
from empire.features.yuanhang.contract import (
    FINANCIAL_JOB,
    FINANCIAL_PROJECT,
    PRICE_JOB,
    PRICE_PROJECT,
    SOURCE,
)
from empire.features.yuanhang.query import YuanhangDataPlugin
from empire.features.yuanhang.ui import YuanhangUiPlugin


def bundle(cfg):
    return FeatureBundle('yuanhang', plugins=(
        OrderedContribution(40000, YuanhangDataPlugin(cfg.get('redis', {}).get('namespace'))),
        OrderedContribution(40010, YuanhangCollector()),
        OrderedContribution(40020, YuanhangCollector(financial=True)),
        OrderedContribution(40030, YuanhangUiPlugin()),
    ), tasks=tuple(OrderedContribution(order, TaskContribution(project, title, capability, SOURCE,
        description, category='行情数据', source_name='同花顺远航版', parallel_downloads=True, unit_name='只股票',
        default_schedule=TaskDefaults('daily', description='每天北京时间18:00维护；日线按覆盖增量及轮转核验，金融联合核验；计划可编辑。'),
        fresh_description='重新核实当前股票池完整来源历史；保留已有事实，按完整单元更新修订。'))
        for order, project, title, capability, description in (
            (40000, PRICE_PROJECT, '远航版完整历史日线', 'collector.yuanhang_prices', '上市至今不复权日线；初始化后按日期增量，5交易日回看及20交易日历史轮转'),
            (40010, FINANCIAL_PROJECT, '远航版权息与股本历史', 'collector.yuanhang_financial', '每证券一次联合响应；分红、送转、配股及三种股本'),
        )), datasets=(OrderedContribution(40000, DatasetContribution(dataset, 'incremental',
            {PRICE_JOB: PRICE_PROJECT, FINANCIAL_JOB: FINANCIAL_PROJECT})),))



