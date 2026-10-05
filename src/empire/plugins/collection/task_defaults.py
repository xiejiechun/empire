"""Recommended initial schedules; saved user policies always take precedence."""
from dataclasses import dataclass


@dataclass(frozen=True)
class TaskDefaults:
    mode: str
    interval_seconds: int = 86400
    daily_time: str = '18:00'
    description: str = ''

    def policy(self, value):
        return {**value, 'mode': self.mode, 'interval_seconds': self.interval_seconds,
                'daily_time': self.daily_time}

HISTORICAL_DAY_DEFAULTS = TaskDefaults('daily', description=(
    '建议默认计划：每天北京时间 18:00。首次补历史，以后补新增日及缺口，'
    '每周复核最近五个交易日；可按需修改执行方式和时间。'))
