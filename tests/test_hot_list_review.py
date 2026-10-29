from datetime import date, timedelta

import pytest

from empire.features.hot_list.review import review_due

CODE = "600198.SH"


@pytest.mark.parametrize("status", [None, "pending"])
def test_missing_history_is_immediate_on_every_day(status):
    for offset in range(30):
        assert review_due(CODE, "2002-08-02", status, str(date(2026, 10, 23) + timedelta(offset)))


@pytest.mark.parametrize("status", ["present", "partial", "source_empty"])
def test_recent_seven_days_are_always_checked(status):
    for offset in range(7):
        for age in range(7):
            today = date(2026, 10, 23) + timedelta(offset)
            assert review_due(CODE, str(today - timedelta(age)), status, str(today))


@pytest.mark.parametrize("status", ["present", "partial", "source_empty"])
def test_warm_detail_has_one_slot_in_every_seven_day_window(status):
    for offset in range(30):
        dates = [date(2026, 10, 23) + timedelta(offset + i) for i in range(7)]
        assert sum(review_due(CODE, "2026-10-01", status, str(d)) for d in dates) == 1


@pytest.mark.parametrize("status", ["partial", "source_empty"])
def test_old_quality_gap_has_one_slot_in_every_thirty_day_window(status):
    for offset in range(35):
        dates = [date(2026, 10, 23) + timedelta(offset + i) for i in range(30)]
        assert sum(review_due(CODE, "2002-08-02", status, str(d)) for d in dates) == 1


def test_complete_old_detail_and_age_boundaries():
    stamp = date(2026, 7, 26)
    for age in range(90, 130):
        assert not review_due(CODE, str(stamp), "present", str(stamp + timedelta(age)))
    # Each boundary is exercised over a complete slot cycle, independent of the hash value.
    for age in (7, 89):
        selected = 0
        for offset in range(70):
            day = date(2026, 10, 23) + timedelta(offset)
            selected += review_due(CODE, str(day - timedelta(age)), "present", str(day))
        assert 0 < selected < 70


def test_repeated_same_business_key_is_deterministic():
    values = [review_due(CODE, "2026-09-01", "present", "2026-10-23") for _ in range(10)]
    assert len(set(values)) == 1
