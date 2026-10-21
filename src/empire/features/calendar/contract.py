"""Business-owned calendar.contract."""
import calendar
import re
from collections.abc import Iterable
from datetime import date, datetime, time, timedelta
from typing import Any, Literal, Protocol, overload

from empire.contracts.archive_version import ArchiveVersion
from empire.core.time import CHINA

# Raw source dictionaries are checked field by field by validate_rows below.
# Keeping this explicit Any boundary avoids pretending an annotation validates JSON.
type RawCalendarRow = dict[str, Any]


class CalendarDayRow(Protocol):
    """The two typed fields consumed from an existing SQL mapping; no copying."""

    @overload
    def __getitem__(self, key: Literal['trade_date']) -> date: ...

    @overload
    def __getitem__(self, key: Literal['is_trade']) -> int: ...


FINGERPRINT_NAMESPACE = "calendar"


FINGERPRINT_VERSION = ArchiveVersion(("utc",), observed_index=0)


FIRST_DATE = date(1990, 12, 19)


def month_start(month: str) -> date:
    if not isinstance(month, str) or not re.fullmatch(r"\d{4}-\d{2}", month):
        raise ValueError("月份必须为 YYYY-MM")
    return date.fromisoformat(month + "-01")


def month_dates(month: str) -> list[date]:
    start = month_start(month)
    end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
    start = max(start, FIRST_DATE)
    return [start + timedelta(days=i) for i in range(max(0, (end - start).days + 1))]


def months_between(start: str, end: str) -> list[str]:
    first, last = month_start(start), month_start(end)
    if first > last:
        return []
    return [f"{index // 12:04d}-{index % 12 + 1:02d}"
            for index in range(first.year * 12 + first.month - 1, last.year * 12 + last.month)]


def validate_rows(month: str, rows: object) -> list[RawCalendarRow]:
    if not isinstance(rows, list) or not 1 <= len(rows) <= 31:
        raise ValueError(f"{month} 来源月份为空或条数无效，不当作全月休市")
    clean: list[RawCalendarRow] = []
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"trade_date", "is_trade"}
                or type(row["is_trade"]) is not bool or not isinstance(row["trade_date"], str)):
            raise ValueError("交易日历仅允许规范化日期和交易标志")
        day = date.fromisoformat(row["trade_date"])
        if day.isoformat() != row["trade_date"]:
            raise ValueError("日期格式必须为 YYYY-MM-DD")
        clean.append(dict(row))
    clean.sort(key=lambda row: row["trade_date"])
    if [row["trade_date"] for row in clean] != [day.isoformat() for day in month_dates(month)]:
        raise ValueError(f"{month} 日期重复、跨月或月份不完整，不覆盖已有日历")
    return clean


A_SHARE_DAY_END = time(15, 30)


def last_closed_trade_day(
    rows: Iterable[CalendarDayRow], now: datetime,
) -> tuple[datetime | None, str]:
    now = now.astimezone(CHINA)
    calendar: dict[date, int] = {}
    for row in rows:
        day, flag = row['trade_date'], row['is_trade']
        if day in calendar or flag not in (0, 1):
            return None, '交易日历包含重复日期或无效交易标记，不能推断收市日期'
        calendar[day] = flag
    if now.date() not in calendar:
        return None, '交易日历缺少今天，不能按周末或法定假期自行推断'
    candidates = [day for day, flag in calendar.items() if flag == 1 and
                  (day < now.date() or day == now.date() and now.time().replace(tzinfo=None) >= A_SHARE_DAY_END)]
    if not candidates:
        return None, '交易日历未提供最近一个已结束交易日'
    required = max(candidates)
    day = required
    while day <= now.date():
        if day not in calendar:
            return None, f'交易日历缺少 {day}，不能越过未知日期确认完整'
        day += timedelta(days=1)
    cutoff = datetime.combine(required, A_SHARE_DAY_END, CHINA)
    phase = '交易日已到 15:30' if required == now.date() else (
        '今天为来源明确的休市日' if calendar[now.date()] == 0 else '今天交易尚未结束（15:30 前）')
    return cutoff, f'{phase}；日频验收目标为最近已结束交易日 {required} 15:30（北京时间）'
