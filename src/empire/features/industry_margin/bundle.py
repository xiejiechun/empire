"""Industry statistics own one collector, dataset and formal query path."""

from empire.contracts.bundle import FeatureBundle
from empire.contracts.bundle import OrderedContribution as O
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.industry_margin.collector import IndustryMarginCollector
from empire.features.industry_margin.contract import JOB, PROJECT
from empire.features.industry_margin.dataset import IndustryMarginDataset
from empire.features.industry_margin.query import IndustryMarginDataPlugin
from empire.features.industry_margin.ui import IndustryMarginUiPlugin


def bundle(cfg):
    return FeatureBundle(
        "industry_margin",
        plugins=(
            O(18600, IndustryMarginDataPlugin(cfg["redis"].get("namespace", "empire"))),
            O(18700, IndustryMarginCollector()),
            O(18800, IndustryMarginUiPlugin()),
        ),
        tasks=(
            O(
                6200,
                TaskContribution(
                    PROJECT,
                    "行业融资融券",
                    "collector.tdx_industry_margin",
                    "tdx",
                    "2016年起完整日期补缺；近7日回看及90日轮转历史核验",
                    category="融资融券",
                    source_name="通达信",
                    parallel_downloads=True,
                    unit_name="个日期",
                    default_schedule=TaskDefaults(
                        "daily",
                        daily_time="19:30",
                        description="每天北京时间19:30补缺和修订回看；不重叠。",
                    ),
                    fresh_description="重新核验2016年起所有完整日期，整轮入队后统一等待归档。",
                ),
            ),
        ),
        datasets=(
            O(6200, DatasetContribution(IndustryMarginDataset(), "incremental", {JOB: PROJECT})),
        ),
    )
