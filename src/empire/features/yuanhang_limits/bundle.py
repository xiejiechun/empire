"""Five independent pools and one shared historical reason owner."""
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.yuanhang_limits.collector import LimitCollector
from empire.features.yuanhang_limits.contract import POOLS, SPLIT_POOL, history_project
from empire.features.yuanhang_limits.dataset import LimitDataset
from empire.features.yuanhang_limits.query import LimitQuery
from empire.features.yuanhang_limits.ui import LimitsUiPlugin


def bundle(cfg):
    kinds = [*POOLS, 'reason']
    collectors = [LimitCollector(k, intraday=k != 'reason', scope='recent' if k == SPLIT_POOL else 'all') for k in kinds]
    history = LimitCollector(SPLIT_POOL, scope='history')
    mappings = [LimitDataset(k) for k in kinds]
    return FeatureBundle('yuanhang_limits', plugins=(
        OrderedContribution(41000, LimitQuery(cfg.get('redis', {}).get('namespace', 'empire'), cfg.get('archive', {}))),
        *(OrderedContribution(41010 + i, c) for i, c in enumerate(collectors)),
        OrderedContribution(41020, history),
        OrderedContribution(41030, LimitsUiPlugin()),
    ), tasks=tuple(OrderedContribution(41000 + i, TaskContribution(
        c.project_id, '远航版' + (POOLS[kinds[i]] if kinds[i] != 'reason' else '历史涨跌停原因'), c.capability,
        'ths_yuanhang', ('补齐缺失日期并维护最近5交易日；历史轮转由独立核验任务执行。' if c.pool == SPLIT_POOL
            else '按完整日期池补齐历史、维护新增日和修订；来源空集合不证明历史边界'),
        category='涨跌停分析', source_name='同花顺远航版', parallel_downloads=True,
        default_schedule=(TaskDefaults('daily', description='每日北京时间18:00；近期5交易日和20交易日历史轮转。')
            if kinds[i] == 'reason' else TaskDefaults('interval', interval_seconds=60,
                description='盘中每轮结束60秒后采样，仅Redis变化快照；15:30后核验日终并归档。')),
        fresh_description=('重新核验最近5交易日并补齐缺失日期；老历史修订请执行独立历史核验任务。'
            if c.pool == SPLIT_POOL else '重新核验有界历史批次；保留已归档事实，不清库。'), unit_name='个单元'))
        for i, c in enumerate(collectors)) + (OrderedContribution(41010, TaskContribution(
            history.project_id, '远航版涨停冲刺历史核验', history.capability, 'ths_yuanhang',
            '独立执行已覆盖老历史的20交易日轮转；不阻塞涨停冲刺近期增量。',
            category='历史核验', source_name='同花顺远航版', parallel_downloads=True,
            default_schedule=TaskDefaults('daily', daily_time='18:30',
                description='每天北京时间18:30核验到期老历史，保留20交易日轮转及停机补查。'),
            fresh_description='重新核验已覆盖且位于近期5交易日以外的历史日期；保留业务事实。',
            unit_name='个历史日期池')),), datasets=tuple(OrderedContribution(41000 + i,
            DatasetContribution(m, 'incremental', {m.JOB: m.PROJECT,
                **({history.job_key: history_project(SPLIT_POOL)} if m.pool == SPLIT_POOL else {})}))
            for i, m in enumerate(mappings)))
