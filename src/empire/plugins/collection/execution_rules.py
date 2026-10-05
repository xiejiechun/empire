"""Plugin-owned scheduling contracts, independent of user enable/route choices."""
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionRule:
    mode: str
    interval_seconds: int = 86400
    daily_time: str = '18:00'
    description: str = ''

    def policy(self, value):
        return {**value, 'mode': self.mode, 'interval_seconds': self.interval_seconds,
                'daily_time': self.daily_time}

    def matches(self, value):
        return all(value.get(key) == expected for key, expected in
                   (('mode', self.mode), ('interval_seconds', self.interval_seconds),
                    ('daily_time', self.daily_time)))


HISTORICAL_DAY_RULE = ExecutionRule('daily', description=(
    '执行规则由插件管理：每天北京时间 18:00 检查已结束交易日；首次补历史，'
    '以后补新增日及缺口，每周复核最近五个交易日。无待补或待复核行情时不下载行情；'
    '同一任务不重叠，停用后不启动。'))
