import empire.features.suspensions.dataset as suspensions
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution
from empire.features.suspensions.collector import TdxSuspensionCollector
from empire.features.suspensions.query import SuspensionDataPlugin
from empire.features.suspensions.ui import SuspensionsUiPlugin


def bundle(cfg):
    return FeatureBundle('suspensions', plugins=(
        OrderedContribution(12700, SuspensionDataPlugin(namespace=cfg["redis"].get("namespace", "empire"),
                                                       archive_settings=cfg.get('archive', {}))),
        OrderedContribution(12800, TdxSuspensionCollector()),
        OrderedContribution(15300, SuspensionsUiPlugin()),
    ), tasks=(
        OrderedContribution(4500, TaskContribution("tdx-suspensions", "沪深 A 股历史停复牌（通达信）",
                    "collector.tdx_suspensions", "tdx", "2004-12-27 起逐自然日完整检查 · 停牌 / 复牌 / 全天或临停",
                    interval_seconds=86400, category="交易可实现性", source_name="通达信", parallel_downloads=True, unit_name='个月',
                    fresh_description="从 2004-12-27 起按自然月重新核验至今；保留已归档事件。")),
    ), datasets=(
        OrderedContribution(4500, DatasetContribution(suspensions, "incremental",
                                        {"tdx-suspensions-v1": "tdx-suspensions"}, schema_version=3)),
    ))
