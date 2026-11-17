"""One task and response group, separately checked financing and lending outputs."""

from empire.contracts.bundle import FeatureBundle
from empire.contracts.bundle import OrderedContribution as O
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.margin.collector import MarginCollector
from empire.features.margin.contract import JOB, PROJECT
from empire.features.margin.dataset import MarginDataset
from empire.features.margin.query import MarginDataPlugin


def bundle(cfg):
    return FeatureBundle(
        "margin",
        plugins=(
            O(18300, MarginDataPlugin(cfg["redis"].get("namespace", "empire"))),
            O(18400, MarginCollector()),
        ),
        tasks=(
            O(
                6100,
                TaskContribution(
                    PROJECT,
                    "个股融资融券",
                    "collector.tdx_margin",
                    "tdx",
                    "每股一次10000条完整历史；融资、融券与页面派生指标",
                    category="融资融券",
                    source_name="通达信",
                    parallel_downloads=True,
                    unit_name="只股票",
                    default_schedule=TaskDefaults(
                        "daily",
                        daily_time="19:30",
                        description="每天北京时间19:30完整核验，每股一个响应；不重叠。",
                    ),
                    fresh_description="重新从第一只证券核验全部历史；未完成入队轮次先确认归档。",
                ),
            ),
        ),
        datasets=(O(6100, DatasetContribution(MarginDataset(), "incremental", {JOB: PROJECT})),),
    )
