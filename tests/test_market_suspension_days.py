from datetime import date, datetime

import pytest

from empire.features.suspensions.exclusions import excluded_days


def event(start='2023-11-06 09:30', resume=None, note='连续停牌', kind='full_day'):
    return dict(unified_code='600470.SH', suspended_at=datetime.fromisoformat(start),
                resumed_at=datetime.fromisoformat(resume) if resume else None,
                source_note=note, suspension_type=kind)


@pytest.mark.parametrize('rows,expected', [
    ([event()], {6}),
    ([event(note='')], set()),
    ([event(start='2023-11-06 10:30')], set()),
    ([event(resume='2023-11-08 09:30')], {6, 7}),
    ([event(), event(resume='2023-11-06 10:30', kind='intraday')], set()),
    ([event(resume='2023-11-09 09:30'), event(resume='2023-11-08 09:30')], {6, 7}),
])
def test_explicit_start_unknown_end_and_conflicting_resumptions(rows, expected):
    plan = excluded_days(rows, {'600470.SH'}, date(2023, 11, 6), date(2023, 11, 9))
    assert plan['600470.SH'] == {date(2023, 11, day) for day in expected}


def test_unknown_start_before_query_cannot_prove_continuing_suspension():
    assert excluded_days([event()], {'600470.SH'}, date(2023, 11, 7), date(2023, 11, 9)) == {'600470.SH': set()}
