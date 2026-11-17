"""Industry statistics own one collector, dataset and formal query path."""

from empire.contracts.bundle import FeatureBundle
from empire.contracts.bundle import OrderedContribution as O
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.graymarket.collector import GraymarketCollector
from empire.features.graymarket.contract import JOB, PROJECT
from empire.features.graymarket.dataset import GraymarketDataset
from empire.features.graymarket.query import GraymarketDataPlugin
from empire.features.graymarket.ui import GraymarketUiPlugin


def bundle(cfg):
    return FeatureBundle(
        "graymarket",
        plugins=(
            O(20100, GraymarketDataPlugin(cfg["redis"].get("namespace", "empire"))),
            O(20200, GraymarketCollector(intraday=True)),
            O(20300, GraymarketUiPlugin()),
        ),
        tasks=(
            O(
                6800,
                TaskContribution(
                    PROJECT,
                    "明盘暗盘资金榜",
                    "collector.eastmoney_graymarket",
                    "eastmoney",
                    "盘中Redis快照；收盘近期复核及2026-05-11起历史补缺",
                    category="资金流向",
                    source_name="东方财富",
                    parallel_downloads=True,
                    unit_name="个日期",
                    default_schedule=TaskDefaults(
                        "interval",
                        interval_seconds=60,
                        description="盘中每轮结束60秒后采入Redis；15:30后归档日榜并有界补缺。",
                    ),
                    fresh_description="盘中重新采样；收盘重新核验近三个交易日，历史缺口由后续轮次补齐。",
                ),
            ),
        ),
        datasets=(
            O(6800, DatasetContribution(GraymarketDataset(), "incremental", {JOB: PROJECT})),
        ),
    )
