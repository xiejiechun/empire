from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from empire.features.themes.history_model import (
    BEIJING,
    HistoryError,
    apply_delta,
    delta,
    digest,
    directory,
    expiry,
    instant,
)


def row(key='1', **overrides):
    return dict(theme_id=key, name='题材' + key, parent_id=None, rank_no=1,
                display_order=0, hot_score='100', change_rate='1.2', limit_up_count=2,
                **{}) | overrides


def test_same_count_different_set_and_field_deltas_roundtrip():
    before = directory([row('1'), row('2')])
    after = directory([row('1', rank_no=5, limit_up_count=0), row('3')])
    difference = delta(before, after)
    assert difference['changed'] == {'1': {'rank_no': 5, 'limit_up_count': 0}}
    assert difference['removed'] == ['2']
    assert set(difference['added']) == {'3'}
    assert apply_delta(before, difference) == after
    assert before['1']['rank_no'] == 1
    assert digest(before) != digest(after)


def test_semantically_same_decimal_and_order_have_same_digest():
    a = directory([row('1', change_rate=Decimal('1.200')), row('2')])
    b = directory([row('2'), row('1', change_rate='1.2', hot_score='1E+2')])
    assert a == b
    assert digest(a) == digest(b)
    assert not any(delta(a, b).values())


@pytest.mark.parametrize('rows', [[], [row(), row()], [row(parent_id='missing')],
    [row(parent_id='2'), row('2', parent_id='1')], [row(limit_up_count=None)],
    [row(limit_up_count=True)], [row(change_rate='NaN')], [row(change_rate='Infinity')],
    [row(change_rate='0.000000001')], [row(change_rate=1.2)], [row(hot_score='-1')],
    [row(name='')], [row(rank_no=None)], [row(theme_id='x:y')]])
def test_bad_directory_is_not_a_successful_empty_snapshot(rows):
    with pytest.raises(HistoryError):
        directory(rows)


def test_child_removal_requires_parent_relationship_consistency():
    before = directory([row(), row('2', parent_id='1', rank_no=None)])
    with pytest.raises(HistoryError):
        apply_delta(before, {'added': {}, 'changed': {}, 'removed': ['1']})


def test_delta_cannot_change_identity_or_reintroduce_existing_key():
    before = directory([row()])
    with pytest.raises(HistoryError):
        apply_delta(before, {'added': {}, 'changed': {'1': {'theme_id': '2'}}, 'removed': []})
    with pytest.raises(HistoryError):
        apply_delta(before, {'added': {'1': row()}, 'changed': {}, 'removed': []})


def test_calendar_expiry_is_day_plus_seven_midnight_not_rolling_ttl():
    assert datetime.fromtimestamp(expiry(date(2026, 10, 17)), BEIJING) == datetime(2026, 10, 24, tzinfo=BEIJING)
    assert instant(datetime(2026, 10, 23, 8, tzinfo=BEIJING)) == datetime(2026, 10, 23, tzinfo=UTC)
    with pytest.raises(HistoryError):
        instant(datetime(2026, 10, 23))
