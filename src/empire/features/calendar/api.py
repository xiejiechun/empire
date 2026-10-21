"""Business-owned calendar.api."""
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.engine import Connection

from empire.features.calendar.contract import last_closed_trade_day


def read_trade_day_cutoff(
    conn: Connection, now: datetime,
) -> tuple[datetime | None, str]:
    rows = conn.execute(text('SELECT trade_date,is_trade FROM trade_calendar '
        'WHERE trade_date BETWEEN :start AND :end ORDER BY trade_date'),
        dict(source='cninfo', start=now.date() - timedelta(days=366), end=now.date())).mappings().all()
    return last_closed_trade_day(rows, now)
