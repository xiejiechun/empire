"""Three independently configured source tasks, one official archive path."""

from empire.contracts.bundle import FeatureBundle
from empire.contracts.bundle import OrderedContribution as O
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution, TaskDefaults
from empire.features.etf_fundamentals import nav_dataset, share_dataset
from empire.features.etf_fundamentals.collector import Collector
from empire.features.etf_fundamentals.contract import PROJECTS
from empire.features.etf_fundamentals.query import Query
from empire.features.etf_fundamentals.ui import Ui


def bundle(cfg):
    collectors = [Collector(project) for project in PROJECTS]
    titles = ("上交所ETF每日份额", "深交所ETF每日份额", "ETF历史净值明细")
    names = ("上交所", "深交所", "天天基金")
    tasks = tuple(
        O(
            40400 + i,
            TaskContribution(
                c.project_id,
                titles[i],
                c.capability,
                c.source,
                "完整来源集合、近期优先及有界历史补缺；不以成交量代替份额",
                category="基金数据",
                source_name=names[i],
                parallel_downloads=True,
                unit_name="个完整日期" if i < 2 else "只ETF",
                default_schedule=TaskDefaults(
                    "interval",
                    interval_seconds=43200,
                    description="每轮结束等待12小时；先补近期，再有界补历史，深市次日复核。",
                ),
                fresh_description="重新核验有界历史单元，保留范围外历史；普通采集继续补缺。",
            ),
        )
        for i, c in enumerate(collectors)
    )
    return FeatureBundle(
        "etf_fundamentals",
        plugins=tuple(
            O(40400 + i, p)
            for i, p in enumerate(
                (Query(cfg.get("redis", {}).get("namespace", "empire")), *collectors, Ui())
            )
        ),
        tasks=tasks,
        datasets=(
            O(
                40400,
                DatasetContribution(
                    share_dataset,
                    "incremental",
                    {c.job_key: c.project_id for c in collectors[:2]},
                    archive_tables=share_dataset.TABLES,
                ),
            ),
            O(
                40401,
                DatasetContribution(
                    nav_dataset,
                    "incremental",
                    {collectors[2].job_key: collectors[2].project_id},
                    archive_tables=nav_dataset.TABLES,
                ),
            ),
        ),
    )
