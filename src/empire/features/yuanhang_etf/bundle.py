"""One ETF feature with independently scheduled directory, history and live tasks."""
from empire.contracts.bundle import FeatureBundle
from empire.contracts.bundle import OrderedContribution as O
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.yuanhang_etf import catalog_dataset, price_dataset
from empire.features.yuanhang_etf.catalog_collector import CatalogCollector
from empire.features.yuanhang_etf.latest import LatestQuery
from empire.features.yuanhang_etf.live import LiveCollector
from empire.features.yuanhang_etf.price_collector import PriceCollector
from empire.features.yuanhang_etf.price_query import PriceQuery
from empire.features.yuanhang_etf.query import CatalogQuery
from empire.features.yuanhang_etf.ui import EtfUiPlugin


def bundle(cfg):
    namespace, archive = cfg.get('redis', {}).get('namespace', 'empire'), cfg.get('archive', {})
    catalog, prices, live = CatalogCollector(), PriceCollector(), LiveCollector()
    titles = ('ETF目录', 'ETF日K', 'ETF最新行情')
    descriptions = ('远航版ETF基金完整动态集合；不混入股票目录',
        '来源不复权日K；最近十交易日优先，每轮另补最多64只ETF历史',
        '沪深ETF基础报价和来源净值，仅Redis最新值；来源报价时间及净值日期未知')
    tasks = tuple(O(40300+i, TaskContribution(c.project_id, titles[i], c.capability,
        'ths_yuanhang', descriptions[i], category='基金数据', source_name='同花顺远航版',
        parallel_downloads=i != 0, unit_name='只ETF',
        default_schedule=(TaskDefaults('interval', interval_seconds=60,
            description='每轮结束等待60秒；正式交易日09:15～11:30、13:00～15:05采样，盘外可手动采样一次。') if i == 2
            else TaskDefaults('daily', daily_time='18:00', description='每天北京时间18:00，目录先准备，下游独立维护。')),
        fresh_description=('完整刷新ETF目录，退出者标记无效并保留历史。' if i == 0 else
            '重新核验所选ETF全部来源历史，保留范围外历史。' if i == 1 else
            '重新采样一次，仅替换完整合法的Redis最新结果，不生成盘中历史。')))
        for i, c in enumerate((catalog, prices, live)))
    return FeatureBundle('yuanhang_etf', plugins=tuple(O(40300+i, p) for i, p in enumerate((
        CatalogQuery(namespace, archive), PriceQuery(namespace, archive), LatestQuery(), catalog, prices, live, EtfUiPlugin()))),
        tasks=tasks, datasets=(O(40300, DatasetContribution(catalog_dataset, 'incremental',
            {catalog.job_key: catalog.project_id, live.job_key: live.project_id})),
            O(40301, DatasetContribution(price_dataset, 'incremental', {prices.job_key: prices.project_id}))))
