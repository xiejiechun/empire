"""Recommended initial schedules; saved user policies always take precedence."""
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskDefaults:
    mode: str
    interval_seconds: int = 86400
    daily_time: str = '18:00'
    description: str = ''

    def policy(self, value: Mapping[str, object]) -> dict[str, object]:
        return {**value, 'mode': self.mode, 'interval_seconds': self.interval_seconds,
                'daily_time': self.daily_time}

HISTORICAL_DAY_DEFAULTS = TaskDefaults('daily', description=(
    '建议默认计划：每天北京时间 18:00。首次补历史，以后补新增日及缺口，'
    '每周复核最近五个交易日；可按需修改执行方式和时间。'))



@dataclass(frozen=True)
class TaskContribution:
    id: str
    name: str
    capability: str
    rate_group: str
    description: str
    interval_seconds: int = 86400
    category: str = "其他"
    source_name: str = ""
    parallel_downloads: bool = False
    default_enabled: bool = True
    fresh_description: str = "创建新批次；已归档数据按对应业务规则保留。"
    default_schedule: TaskDefaults | None = None
    unit_name: str = "个单元"
