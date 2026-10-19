"""Freeze the most recent Friday's revision review in each resumable round."""
from datetime import datetime, time, timedelta

from empire.core.time import CHINA


def review_token(now=None):
    now = (now or datetime.now(CHINA)).astimezone(CHINA)
    day = now.date() - timedelta(days=(now.weekday() - 4) % 7)
    if now.date() == day and now.time().replace(tzinfo=None) < time(18):
        day -= timedelta(days=7)
    return day.isoformat()


def review_days(days, previous, now=None):
    token = review_token(now)
    return token, [d.isoformat() for d in days[-5:]] if previous != token else []
