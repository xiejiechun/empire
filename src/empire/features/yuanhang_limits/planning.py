"""Date-unit incremental planning; SQL coverage survives volatile Redis state."""
from dataclasses import dataclass
from datetime import date, timedelta

from empire.features.yuanhang_limits.contract import day_value


@dataclass(frozen=True)
class PoolPlan:
    days: tuple[str, ...]
    missing: int
    due: int
    remaining: int
    pending: tuple[str, ...]


def calendar_dates(rows, through):
    """Validate every calendar day, including source-declared closed days."""
    start = date(1990, 12, 19)
    end = date.fromisoformat(day_value(through))
    if not rows or len(rows) != (end - start).days + 1 or len(rows) > 36600:
        raise ValueError('全历史规划日历缺日或超出100年范围')
    trades = []
    for offset, (day, flag) in enumerate(rows):
        if day != (start + timedelta(days=offset)).isoformat() or type(flag) is not int or flag not in (0, 1):
            raise ValueError('正式日历缺日、重复或交易标记无效')
        if flag:
            trades.append(day)
    if not trades or trades[-1] != through:
        raise ValueError('截止日期不是已验证交易日')
    return trades


def plan_pool(trade_days, coverage, verified, *, cutoff, batch_limit=64,
              lookback=10, force=False, exclude=(), scope='all'):
    """Inputs have one fixed calendar origin; verified maps unit date to check date.

    Coverage contains only validated source units, not guessed empty days.
    A bounded plan is persisted atomically with each queued unit. Rebuilding a
    new plan after Redis loss uses SQL proofs, not the largest successful date.
    """
    day_value(cutoff)
    if scope not in ('all', 'recent', 'backfill'):
        raise ValueError('日期池规划范围无效')
    if (not trade_days or list(trade_days) != sorted(set(trade_days))
            or any(day_value(d) > cutoff for d in trade_days) or trade_days[-1] != cutoff):
        raise ValueError('日期池规划需要有序完整交易日范围和已结束截止日')
    if not 1 <= batch_limit <= 256 or not 1 <= lookback <= 60:
        raise ValueError('日期池规划预算错误')
    domain = set(trade_days)
    if set(coverage) - domain or set(verified) - domain:
        raise ValueError('覆盖证据超出声明历史范围')
    if any(day_value(v) > cutoff for v in verified.values()):
        raise ValueError('核验版本超前')
    missing = domain - set(coverage)
    recent = set(trade_days[-lookback:])
    due = {day for day in recent if force or verified.get(day, '') < cutoff}
    if scope == 'recent':
        work = (missing & recent) | due
    elif scope == 'backfill':
        work = missing - recent
    else:
        work = domain if force else missing | due
    missing &= work
    due &= work
    work -= set(exclude)
    # Recent work never waits behind historical gaps; backfill is a separate run.
    newest = sorted(work & recent, reverse=True)[:batch_limit]
    older = sorted(work - set(newest))[:batch_limit - len(newest)]
    selected = tuple(newest + older)
    pending = tuple(sorted(work - set(selected)))
    return PoolPlan(selected, len(missing), len(due - missing), len(pending), pending)
