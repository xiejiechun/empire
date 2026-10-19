import empire.features.calendar.dataset as trade_calendar
from empire.contracts.bundle import FeatureBundle, OrderedContribution
from empire.contracts.dataset import DatasetContribution
from empire.contracts.task import TaskContribution
from empire.features.calendar.collector import CninfoCalendarCollector
from empire.features.calendar.query import CalendarDataPlugin
from empire.features.calendar.ui import CalendarUiPlugin


def bundle(cfg):
    return FeatureBundle('calendar', plugins=(
        OrderedContribution(12500, CalendarDataPlugin(namespace=cfg["redis"].get("namespace", "empire"),
                                   archive_settings=cfg.get("archive", {}))),
        OrderedContribution(12600, CninfoCalendarCollector()),
        OrderedContribution(15200, CalendarUiPlugin()),
    ), tasks=(
        OrderedContribution(4400, TaskContribution("cninfo-calendar", "大 A 交易日期（巨潮资讯）",
                    "collector.cninfo_calendar", "cninfo", "首次补齐历史 · 后续维护本月至下一年 12 月 · 交易日 / 休市日",
                    interval_seconds=86400, category="基础数据", source_name="巨潮资讯", parallel_downloads=True, unit_name='个月',
                    fresh_description="从 1990-12 起重新核验全部月份至下一年 12 月；正常维护请用立即采集。")),
    ), datasets=(
        OrderedContribution(4400, DatasetContribution(trade_calendar, "incremental",
                                        {"cninfo-calendar-v1": "cninfo-calendar"})),
    ))
