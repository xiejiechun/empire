"""Five independent pools and one shared historical reason owner."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.yuanhang_limits.collector import LimitCollector
from empire.features.yuanhang_limits.contract import POOLS
from empire.features.yuanhang_limits.dataset import LimitDataset
from empire.features.yuanhang_limits.query import LimitQuery
from empire.features.yuanhang_limits.ui import LimitsUiPlugin


def bundle(cfg):
    kinds = [*POOLS, 'reason']
    collectors = [LimitCollector(k, intraday=k != 'reason') for k in kinds]
    mappings = [LimitDataset(k) for k in kinds]
    return FeatureBundle('yuanhang_limits', plugins=(
        OrderedContribution(41000, LimitQuery(cfg.get('redis', {}).get('namespace', 'empire'), cfg.get('archive', {}))),
        *(OrderedContribution(41010 + i, c) for i, c in enumerate(collectors)),
        OrderedContribution(41030, LimitsUiPlugin()),
    ), tasks=tuple(OrderedContribution(41000 + i, TaskContribution(
        c.project_id, '远航版' + (POOLS[kinds[i]] if kinds[i] != 'reason' else '历史涨跌停原因'), c.capability,
        'ths_yuanhang', '按完整日期池补齐历史、维护新增日和修订；来源空集合不证明历史边界',
        category='涨跌停分析', source_name='同花顺远航版', parallel_downloads=True,
        default_schedule=(TaskDefaults('daily', description='每日北京时间18:00；近期5交易日和20交易日历史轮转。')
            if kinds[i] == 'reason' else TaskDefaults('interval', interval_seconds=60,
                description='盘中每轮结束60秒后采样，仅Redis变化快照；15:30后核验日终并归档。')),
        fresh_description='重新核验有界历史批次；保留已归档事实，不清库。', unit_name='个单元'))
        for i, c in enumerate(collectors)), datasets=tuple(OrderedContribution(41000 + i,
            DatasetContribution(m, 'incremental', {m.JOB: m.PROJECT})) for i, m in enumerate(mappings)))
