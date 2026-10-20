"""Original identities and ordered contributions owned by this business."""
from empire.contracts.bundle import FeatureBundle, positioned
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.name_changes.collector import NameChangeCollector
from empire.features.name_changes.contract import KINDS as NAME_KINDS
from empire.features.name_changes.contract import SCHEMA_VERSION as NAME_SCHEMA_VERSION
from empire.features.name_changes.contract import project as name_project
from empire.features.name_changes.dataset import NameDataset
from empire.features.name_changes.query import NameDataPlugin
from empire.features.name_changes.ui import NameUiPlugin


def bundle(cfg):
    return FeatureBundle('name_changes', plugins=(
        *positioned((8600, 8700), (NameDataPlugin(kind, cfg['redis'].get('namespace', 'empire'), cfg.get('archive', {})) for kind in NAME_KINDS)),
        *positioned((8800, 8900), (NameChangeCollector(kind) for kind in NAME_KINDS)),
        *positioned((9000, 9100), (NameUiPlugin(kind) for kind in NAME_KINDS)),
    ), tasks=(
        *positioned((2300, 2400), (TaskContribution(name_project(kind), item[0] + '（通达信）',
                    'collector.tdx_' + kind + '_renames', 'tdx', '一次完整历史响应；缺名及链断裂独立显示',
                    category='证券基础', source_name='通达信', unit_name='次完整响应', default_schedule=TaskDefaults('daily',
                        description='每天北京时间18:00核验全部历史，一次请求发现新增与历史修订；可编辑计划。'),
                    fresh_description='核验来源全部更名历史；已入队轮次先完成归档，缺失名称保持未知。')
                    for kind, item in NAME_KINDS.items())),
    ), datasets=(
        *positioned((2600, 2700), (DatasetContribution(NameDataset(kind), 'incremental',
                        {NameDataset(kind).JOB: NameDataset(kind).PROJECT}, schema_version=NAME_SCHEMA_VERSION) for kind in NAME_KINDS)),
    ))
