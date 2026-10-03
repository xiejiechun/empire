import pytest

from empire.contracts.collection_integrity import confirmed_distinct_records, require_complete_set


def test_equal_raw_count_does_not_hide_repeated_key_and_missing_record():
    with pytest.raises(ValueError, match='业务键重复'):
        require_complete_set(['A', 'B', 'B'], 3, lambda row: row)


def test_complete_unique_set_and_proven_empty_set():
    assert require_complete_set(['B', 'A'], 2, lambda row: row) == {'A', 'B'}
    assert require_complete_set([], 0, lambda row: row) == set()
    with pytest.raises(ValueError, match='分页取得'):
        require_complete_set(['A'], 2, lambda row: row)


def test_source_repetition_requires_same_content_and_multiplicity():
    a, b = {'id': 'A', 'value': 1}, {'id': 'B', 'value': 2}
    def key(row):
        return row['id']
    assert confirmed_distinct_records([a, a, b], [b, a, a], key) == [a, b]
    with pytest.raises(ValueError, match='复核不一致'):
        confirmed_distinct_records([a, a, b], [a, b, b], key)
    other = {**a, 'value': 3}
    with pytest.raises(ValueError, match='内容冲突'):
        confirmed_distinct_records([a, other], [other, a], key)
