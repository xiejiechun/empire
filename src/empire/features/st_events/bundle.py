"""Original identities and ordered contributions owned by this business."""
from empire.contracts.bundle import FeatureBundle, positioned
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.st_events.collector import StEventCollector
from empire.features.st_events.contract import KINDS as ST_KINDS
from empire.features.st_events.contract import SCHEMA_VERSION as ST_SCHEMA_VERSION
from empire.features.st_events.contract import project as st_project
from empire.features.st_events.dataset import StDataset
from empire.features.st_events.query import StDataPlugin
from empire.features.st_events.ui import StUiPlugin


def bundle(cfg):
    return FeatureBundle('st_events', plugins=(
        *positioned((9200, 9300), (StDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in ST_KINDS)),
        *positioned((9400, 9500), (StEventCollector(kind) for kind in ST_KINDS)),
        *positioned((9600, 9700), (StUiPlugin(kind) for kind in ST_KINDS)),
    ), tasks=(
        *positioned((2100, 2200), (TaskContribution(st_project(kind), item[0] + '（通达信）',
                    'collector.tdx_st_' + kind, 'tdx', '全部来源历史单响应；日期、前后简称、原因及行业',
                    category='交易状态', source_name='通达信', unit_name='次完整响应',
                    default_schedule=TaskDefaults('daily', description='每天北京时间18:00完整核验历史，发现新增及修订；计划可编辑。'),
                    fresh_description='重新核验来源全部历史；已入队轮次先完成归档，不裁定每日ST状态。')
                    for kind, item in ST_KINDS.items())),
    ), datasets=(
        *positioned((2400, 2500), (DatasetContribution(StDataset(kind), 'incremental',
                        {StDataset(kind).JOB: StDataset(kind).PROJECT}, schema_version=ST_SCHEMA_VERSION) for kind in ST_KINDS)),
    ))
