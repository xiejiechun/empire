from datetime import datetime

from empire.core.time import CHINA
from empire.features.themes.bundle import bundle
from empire.features.themes.query import daily_review_due


def test_daily_review_uses_close_boundary_and_calendar_day_not_24h():
    def at(day, hour, minute=0):
        return datetime(2026, 10, day, hour, minute, tzinfo=CHINA)
    assert not daily_review_due(at(26, 12), at(26, 14))
    assert daily_review_due(at(26, 12), at(26, 18))
    assert not daily_review_due(at(26, 18), at(26, 19))
    assert daily_review_due(at(25, 19), at(26, 18))
    assert not daily_review_due(at(26, 15, 30), at(26, 18))


def test_daily_defaults_keep_list_before_details():
    schedules = [item.value.default_schedule for item in bundle({}).tasks]
    assert [(s.mode, s.daily_time) for s in schedules] == [('daily', '18:00'), ('daily', '18:10')]
