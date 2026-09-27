"""Explicit time conversion at the MySQL boundary.

Redis messages retain timezone-aware instants. MySQL DATETIME columns store naive
Asia/Shanghai wall-clock values so direct database inspection matches the product.
"""
from datetime import datetime, timedelta, timezone

CHINA = timezone(timedelta(hours=8))


def mysql_time(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("MySQL business time conversion requires a timezone")
    return value.astimezone(CHINA).replace(tzinfo=None)


def mysql_iso(value: datetime) -> str:
    return mysql_time(value).isoformat(timespec="microseconds")
