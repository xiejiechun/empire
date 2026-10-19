"""Business-owned calendar.api."""
from datetime import timedelta

from sqlalchemy import text

from empire.features.calendar.contract import last_closed_trade_day


def read_trade_day_cutoff(conn, now):
    rows = conn.execute(text('SELECT trade_date,is_trade FROM trade_calendar '
        'WHERE trade_date BETWEEN :start AND :end ORDER BY trade_date'),
        dict(source='cninfo', start=now.date() - timedelta(days=366), end=now.date())).mappings().all()
    return last_closed_trade_day(rows, now)
