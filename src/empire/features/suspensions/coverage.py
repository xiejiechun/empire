"""Business-owned suspensions.coverage."""
from datetime import datetime, timedelta

from empire.core.time import CHINA


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
