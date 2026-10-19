"""Read-only calendar acceptance: SQL contents plus optional current archive proofs."""
import asyncio
from datetime import datetime

from empire.core.time import CHINA
from empire.features.calendar.audit_rules import audit_calendar
from empire.features.calendar.contract import (
    FINGERPRINT_NAMESPACE,
    FINGERPRINT_VERSION,
    months_between,
    validate_rows,
)
from empire.features.calendar.snapshot import calendar_snapshot
from empire.features.preparation.evidence import freshness
from empire.plugins.pipeline.fingerprints import FingerprintCache, digest


def merge_confirmations(rows, state, proofs, now):
    observed = dict(state.get('observed', {}))
    accepted = []
    grouped = {}
    for row in rows:
        if row['is_trade'] not in (0, 1):
            continue
        day = row['trade_date'].isoformat()
        grouped.setdefault(day[:7], []).append({'trade_date': day, 'is_trade': bool(row['is_trade'])})
    for month, proof in proofs.items():
        try:
            stamp = FINGERPRINT_VERSION.key(proof['version'], now=now)[0]
            content = validate_rows(month, grouped.get(month, []))
            if digest(content) != proof['hash']:
                continue
            previous = observed.get(month)
            if previous:
                if freshness(previous, now, month).status == 'fail':
                    continue
                if stamp <= datetime.fromisoformat(previous):
                    continue
            observed[month] = stamp.isoformat()
            accepted.append(month)
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    return {**state, 'observed': observed}, accepted


async def check_calendar(plugin):
    now = datetime.now(CHINA)
    rows, state = await plugin.mysql.read(calendar_snapshot, plugin)
    months = months_between(now.strftime('%Y-%m'), f'{now.year + 1}-12')
    store = plugin.context.optional('redis.store') if plugin.context else None
    proofs, note = {}, 'Redis 未启用，使用 SQL 确认'
    if store is not None:
        try:
            cache = FingerprintCache(store, plugin.archive_settings, lambda _: FINGERPRINT_VERSION)
            proofs = await asyncio.wait_for(cache.peek(FINGERPRINT_NAMESPACE, plugin.source, months), timeout=3)
            note = '已只读核对 Redis 摘要、版本、到期索引与 SQL 月份内容'
        except Exception:
            note = 'Redis 证据暂不可用，使用 SQL 确认'
    combined, accepted = merge_confirmations(rows, state, proofs, now)
    return audit_calendar(rows, combined, now, cache_months=accepted, cache_note=note)
