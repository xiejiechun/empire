"""Business-owned suspensions.coverage."""
import asyncio
from datetime import date, datetime, timedelta

from empire.core.time import CHINA
from empire.features.suspensions.contract import (
    FINGERPRINT_NAMESPACE,
    FINGERPRINT_VERSION,
    FIRST_DATE,
    coverage_identity,
)
from empire.plugins.pipeline.fingerprints import FingerprintCache, digest


async def confirmed_coverage(coverage, store, settings, now):
    """Supplement time only, for an exact already-SQL-covered archive range."""
    if store is None:
        return coverage
    try:
        first, last = date.fromisoformat(coverage['from']), date.fromisoformat(coverage['through'])
        sql_stamp = datetime.fromisoformat(coverage['confirmed_at'])
        if first != FIRST_DATE or last > now.date() or sql_stamp.tzinfo is None or sql_stamp > now:
            return coverage
        # Archive batches stay within a calendar month; at most 31 exact keys.
        candidates = {}
        for offset in range(last.day):
            start = last - timedelta(days=offset)
            if start < first:
                break
            days = [(start + timedelta(days=i)).isoformat() for i in range(offset + 1)]
            candidates[coverage_identity(start.isoformat(), last.isoformat())] = digest({'checked_dates': days})
        cache = FingerprintCache(store, settings, lambda _: FINGERPRINT_VERSION)
        proofs = await asyncio.wait_for(cache.peek(FINGERPRINT_NAMESPACE, 'tdx', list(candidates)), 3)
        newest = sql_stamp
        for key, proof in proofs.items():
            stamp = FINGERPRINT_VERSION.key(proof['version'])[0]
            if proof['hash'] == candidates[key] and sql_stamp <= stamp <= now:
                newest = max(newest, stamp)
        if newest > sql_stamp:
            return {**coverage, 'confirmed_at': newest.isoformat(),
                    'sql_confirmed_at': sql_stamp.isoformat(), 'time_evidence': '匹配的只读统一归档范围摘要'}
    except Exception:
        pass  # Missing, corrupt, expired, offline: independently retain SQL.
    return coverage


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
        return 'pass', f'最近确认 {stamp.astimezone(CHINA).isoformat()} 已覆盖目标交易日结束；休市期间不按自然日过期；' + coverage.get('time_evidence', 'SQL证据')
    except (ValueError, TypeError):
        return 'fail', '停复牌核验时间格式不可信'
