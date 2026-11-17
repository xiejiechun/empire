"""Bounded recent updates anchored to a separately dated full-source verification."""
from datetime import UTC, datetime, timedelta

from empire.features.repurchases.contract import day

FULL_INTERVAL = timedelta(days=3)


def refresh_plan(proof, now):
    try:
        observed = datetime.fromisoformat(proof['observed_at'])
        full = datetime.fromisoformat(proof.get('full_observed_at', proof['observed_at']))
        if (proof.get('contract') not in (1, 2) or type(proof.get('count')) is not int
                or not 0 <= proof['count'] <= 100000 or len(proof['digest']) != 64
                or observed.tzinfo is None or full.tzinfo is None
                or not full <= observed <= now or now - full >= FULL_INTERVAL):
            return None
        bytes.fromhex(proof['digest'])
    except (KeyError, ValueError, TypeError):
        return None
    from empire.core.time import CHINA
    return dict(since=(observed.astimezone(CHINA).date() - timedelta(days=3)).isoformat(),
                full_observed_at=full.astimezone(UTC).isoformat(timespec='microseconds'), proof=False)


def validate_refresh(value, observed):
    if (not isinstance(value, dict) or set(value) != {'since', 'full_observed_at', 'proof'}
            or type(value['proof']) is not bool):
        raise ValueError('回购增量范围证明无效')
    day(value['since'], required=True)
    full = datetime.fromisoformat(value['full_observed_at'])
    if full.tzinfo is None or full > observed:
        raise ValueError('回购全历史核验时间无效')
    return value
