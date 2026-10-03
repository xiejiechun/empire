"""Read-only end-of-day target from explicit CNINFO dates, never weekend inference."""
from datetime import datetime, time, timedelta

from sqlalchemy import text

from empire.core.time import CHINA

# The suspension dataset covers all SH/SZ A shares, including boards with
# after-hours fixed-price trading. This is a dataset verification cutoff,
# not a claim that every stock continuously trades from 09:15 until 15:30.
A_SHARE_DAY_END = time(15, 30)


def last_closed_trade_day(rows, now):
    now = now.astimezone(CHINA)
    calendar = {}
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


def read_trade_day_cutoff(conn, now):
    rows = conn.execute(text('SELECT trade_date,is_trade FROM trade_calendar '
        'WHERE trade_date BETWEEN :start AND :end ORDER BY trade_date'),
        dict(source='cninfo', start=now.date() - timedelta(days=366), end=now.date())).mappings().all()
    return last_closed_trade_day(rows, now)


def coverage_as_of(coverage, now, cutoff):
    if cutoff is None:
        return 'unknown', '无法确定交易日验收目标；先补齐正式交易日历'
    raw = coverage.get('confirmed_at')
    if not raw:
        return 'unknown', '缺少停复牌成功核验时间，不能以记录最新日期替代'
    try:
        stamp = datetime.fromisoformat(raw)
        if stamp.tzinfo is None:
            raise ValueError('timezone missing')
        if stamp > now + timedelta(minutes=5):
            return 'fail', '停复牌核验时间异常超前'
        if stamp < cutoff:
            return 'fail', f'最近确认 {stamp.astimezone(CHINA).isoformat()} 早于目标交易日结束，需收市后复核'
        return 'pass', f'最近确认 {stamp.astimezone(CHINA).isoformat()} 已覆盖目标交易日结束；休市期间不按自然日过期'
    except (ValueError, TypeError):
        return 'fail', '停复牌核验时间格式不可信'
