"""Industry statistics own one collector, dataset and formal query path."""

from empire.contracts.bundle import FeatureBundle
from empire.contracts.bundle import OrderedContribution as O
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.market_margin.collector import MarketMarginCollector
from empire.features.market_margin.contract import JOB, PROJECT
from empire.features.market_margin.dataset import MarketMarginDataset
from empire.features.market_margin.query import MarketMarginDataPlugin
from empire.features.market_margin.ui import MarketMarginUiPlugin


def bundle(cfg):
    return FeatureBundle(
        "market_margin",
        plugins=(
            O(18900, MarketMarginDataPlugin(cfg["redis"].get("namespace", "empire"))),
            O(19000, MarketMarginCollector()),
            O(19100, MarketMarginUiPlugin()),
        ),
        tasks=(
            O(
                6300,
                TaskContribution(
                    PROJECT,
                    "市场融资融券（同花顺）",
                    "collector.ths_market_margin",
                    "ths",
                    "2010年起四市场完整历史；每天四请求全量核验",
                    category="融资融券",
                    source_name="同花顺",
                    parallel_downloads=True,
                    unit_name="个市场",
                    default_schedule=TaskDefaults(
                        "daily",
                        daily_time="19:30",
                        description="每天北京时间19:30核验四市场完整历史；不重叠。",
                    ),
                    fresh_description="重新核验四市场完整序列，整轮入队后统一等待归档。",
                ),
            ),
        ),
        datasets=(
            O(6300, DatasetContribution(MarketMarginDataset(), "incremental", {JOB: PROJECT})),
        ),
    )
