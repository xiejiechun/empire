"""Two independent tasks, one archive dataset; volatile admission shares ownership."""
from empire.contracts.bundle import FeatureBundle
from empire.contracts.bundle import OrderedContribution as O
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.fx import dataset
from empire.features.fx.collector import FxDailyCollector
from empire.features.fx.contract import DAILY_JOB, DAILY_PROJECT, LIVE_JOB, LIVE_PROJECT
from empire.features.fx.live import FxLatestQuery, FxLiveCollector
from empire.features.fx.query import FxDailyQuery
from empire.features.fx.ui import FxUiPlugin


def bundle(cfg):
    return FeatureBundle('fx', plugins=(O(20400, FxLatestQuery()), O(20500, FxDailyQuery()),
        O(20600, FxLiveCollector()), O(20700, FxDailyCollector()), O(20800, FxUiPlugin())),
        tasks=(O(6900, TaskContribution(LIVE_PROJECT, '汇率实时行情', 'collector.ths_fx_live',
            'ths', '十二品种仅Redis最新值；不保留分钟历史', category='外汇数据', source_name='同花顺远航版',
            parallel_downloads=True, unit_name='个品种', default_schedule=TaskDefaults('interval', interval_seconds=60,
                description='每轮结束等待60秒，仅更新Redis最新行情。'), fresh_description='重新采样最新值，不生成历史快照。')),
            O(7000, TaskContribution(DAILY_PROJECT, '汇率历史日线', 'collector.ths_fx_daily', 'ths',
                '来源日K线；逐年补缺及最近30自然日修订', category='外汇数据', source_name='同花顺远航版',
                parallel_downloads=True, unit_name='个品种', default_schedule=TaskDefaults('daily', daily_time='09:00',
                    description='每天北京时间09:00集中补缺和归档，排除当日K线。'),
                fresh_description='重新核验全部来源年份，接收较早历史修订；不删除来源范围外数据。'))),
        datasets=(O(6900, DatasetContribution(dataset, 'incremental', {DAILY_JOB: DAILY_PROJECT, LIVE_JOB: LIVE_PROJECT})),))
