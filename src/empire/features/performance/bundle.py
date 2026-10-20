"""Six original business identities and contribution slots, with one owner."""
from empire.contracts.bundle import FeatureBundle, positioned
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.performance.collector import PerformanceCollector
from empire.features.performance.contract import UNIT_KINDS as PERFORMANCE_KINDS
from empire.features.performance.contract import project as performance_project
from empire.features.performance.dataset import PerformanceDataset
from empire.features.performance.query import PerformanceDataPlugin
from empire.features.performance.ui import PerformanceUiPlugin


def bundle(cfg):
    return FeatureBundle("performance", plugins=(
        *positioned((1100, 1200, 1300, 1400, 1500, 1600), (PerformanceDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in PERFORMANCE_KINDS)),
        *positioned((1700, 1800, 1900, 2000, 2100, 2200), (PerformanceCollector(kind) for kind in PERFORMANCE_KINDS)),
        *positioned((2300, 2400, 2500, 2600, 2700, 2800), (PerformanceUiPlugin(kind) for kind in PERFORMANCE_KINDS)),
    ), tasks=(
        *positioned((500, 600, 700, 800, 900, 1000), (TaskContribution(performance_project(kind), item[0] + '（通达信）',
                    'collector.tdx_' + kind, 'tdx', '每页10000；完整来源单元、历史回查及结构化查询',
                    category=item[3], source_name='通达信', parallel_downloads=True, unit_name='个完整响应',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整回查来源单元历史；首次补来源可得范围，可编辑。'),
                    fresh_description='下载阶段重新建立完整来源范围；待归档阶段先确认原轮次；保留所有已归档历史。')
                    for kind, item in PERFORMANCE_KINDS.items())),
    ), datasets=(
        *positioned((500, 600, 700, 800, 900, 1000), (DatasetContribution(PerformanceDataset(kind), 'incremental',
                        {PerformanceDataset(kind).JOB: PerformanceDataset(kind).PROJECT}) for kind in PERFORMANCE_KINDS)),
    ))
