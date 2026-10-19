"""Business-owned preparation.evidence."""
from datetime import datetime, timedelta

from empire.contracts.preparation import CheckEvidence
from empire.core.time import CHINA


def evidence(ident, passed, measured):
    return CheckEvidence(ident, 'pass' if passed else 'fail', measured)


def freshness(value, now, label, *, naive_china=False):
    if not value:
        return CheckEvidence('freshness', 'unknown', f'{label}：缺少成功核验时间；内容更新时间不能替代')
    try:
        if not isinstance(value, str) or len(value) < 19:
            raise ValueError('missing time')
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            if not naive_china:
                raise ValueError('missing timezone')
            stamp = stamp.replace(tzinfo=CHINA)
        age = now - stamp
        if age < -timedelta(minutes=5):
            return evidence('freshness', False, f'{label}：核验时间异常超前 {value}')
        if age <= timedelta(days=3):
            return evidence('freshness', True, f'{label}：{stamp.astimezone(CHINA).isoformat()}，不超过 3 天')
        return CheckEvidence('freshness', 'unknown', f'{label} SQL 核验上界 {value} 已超过 3 天；'
                             '缓存命中可能更新了 Redis，本检查未核验缓存，不能确认最新时效')
    except (ValueError, TypeError):
        return evidence('freshness', False, f'{label}：成功核验时间格式不可信')
