from datetime import UTC, datetime

from empire.core.time import mysql_time
from empire.plugins.ui.common import local_date


def test_mysql_business_time_is_beijing_wall_clock_and_ui_does_not_add_twice():
    instant = datetime(2026, 9, 26, 4, 30, tzinfo=UTC)
    stored = mysql_time(instant)
    assert stored == datetime(2026, 9, 26, 12, 30)
    assert local_date(stored.isoformat()) == "2026-09-26 12:30"
