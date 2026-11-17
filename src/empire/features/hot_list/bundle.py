"""One shared response serves independently checked summary and seat outputs."""

from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.hot_list.collector import HotListCollector
from empire.features.hot_list.contract import JOB, PROJECT
from empire.features.hot_list.dataset import HotListDataset
from empire.features.hot_list.query import HotListDataPlugin
from empire.features.hot_list.ui import HotListUiPlugin


def bundle(cfg):
    return FeatureBundle(
        "hot_list",
        plugins=(
            OrderedContribution(
                18000,
                HotListDataPlugin(cfg["redis"].get("namespace", "empire"), cfg.get("archive", {})),
            ),
            OrderedContribution(18100, HotListCollector()),
            OrderedContribution(18200, HotListUiPlugin()),
        ),
        tasks=(
            OrderedContribution(
                6000,
                TaskContribution(
                    PROJECT,
                    "个股龙虎榜",
                    "collector.tdx_hot_list",
                    "tdx",
                    "首次全部历史；补缺及7/30日轮转回查；单日与多日榜分别保留",
                    category="交易事件",
                    source_name="通达信",
                    parallel_downloads=True,
                    unit_name="只股票",
                    default_schedule=TaskDefaults(
                        "daily",
                        daily_time="19:30",
                        description="每天北京时间19:30执行一次；不重叠。",
                    ),
                    fresh_description="强制重新核验全部证券、全部历史日期；保留已归档历史，接收有效来源修订。",
                ),
            ),
        ),
        datasets=(
            OrderedContribution(
                6000, DatasetContribution(HotListDataset(), "incremental", {JOB: PROJECT})
            ),
        ),
    )
