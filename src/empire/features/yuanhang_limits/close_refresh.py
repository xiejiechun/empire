"""Bounded post-close freshness windows, owned by the existing pool task."""
from datetime import time

from empire.core.time import CHINA


def refresh_slot(now):
    local = now.astimezone(CHINA)
    if local.time().replace(tzinfo=None) < time(16):
        return None
    minute = min(local.hour * 60 + local.minute, 21 * 60)
    return local.replace(hour=minute // 60, minute=minute % 60 // 30 * 30,
                         second=0, microsecond=0).isoformat(timespec='minutes')


async def today_plan(query, now, *, exclude=()):
    from empire.features.calendar.api import read_trade_day_cutoff

    cutoff, message = await query.read(lambda conn: read_trade_day_cutoff(conn, now))
    if cutoff is None:
        raise ValueError(message)
    day = now.astimezone(CHINA).date().isoformat()
    slot = refresh_slot(now)
    units = [day] if slot and cutoff.date().isoformat() == day and day not in exclude else []
    return dict(units=units, cutoff=day, remaining=0, pending=[], close_slot=slot)
