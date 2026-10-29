from datetime import date, timedelta

import pytest

from empire.sources.yuanhang_ranges import contiguous_through, expand_versions, replace_range

OLD = '2026-10-23T01:00:00.000000+00:00'
NEW = '2026-10-23T02:00:00.000000+00:00'
LATEST = '2026-10-23T03:00:00.000000+00:00'


def apply(old, new, start, end, version, segments):
    return replace_range(old, new, year=2026, start=start, end=end, observed=version, segments=segments)


def test_partial_replacement_preserves_other_dates_and_authoritative_deletion():
    rows, segments, accepted = apply(
        [['2026-01-02', 1], ['2026-01-05', 2], ['2026-01-06', 3]],
        [['2026-01-05', 4]], '2026-01-05', '2026-01-06', NEW,
        [['2026-01-01', '2026-01-06', OLD]])
    assert rows == [['2026-01-02', 1], ['2026-01-05', 4]]
    assert accepted == ['2026-01-05', '2026-01-06']
    assert contiguous_through(segments, 2026) == '2026-01-06'


def test_old_full_response_cannot_overwrite_new_point_or_resurrect_deleted_point():
    old = [['2026-01-02', 1], ['2026-01-05', 4]]
    segments = [['2026-01-01', '2026-01-04', OLD], ['2026-01-05', '2026-01-06', LATEST]]
    rows, versions, accepted = apply(old, [['2026-01-02', 2], ['2026-01-05', 1], ['2026-01-06', 3]],
                                     '2026-01-01', '2026-01-06', NEW, segments)
    assert rows == [['2026-01-02', 2], ['2026-01-05', 4]]
    assert '2026-01-05' not in accepted and '2026-01-06' not in accepted
    assert versions[-1][-1] == LATEST


def test_older_disjoint_range_is_still_accepted_and_gaps_remain_visible():
    rows, versions, accepted = apply([['2026-01-05', 4]], [['2026-01-02', 2]],
        '2026-01-01', '2026-01-02', OLD, [['2026-01-05', '2026-01-06', NEW]])
    assert rows == [['2026-01-02', 2], ['2026-01-05', 4]]
    assert contiguous_through(versions, 2026) == '2026-01-02'
    assert len(accepted) == 2


def test_replay_is_idempotent_but_equal_version_different_content_fails():
    before = [['2026-01-02', 1]]
    segments = [['2026-01-01', '2026-01-02', OLD]]
    rows, versions, _ = apply(before, before, '2026-01-01', '2026-01-02', OLD, segments)
    assert rows == before and versions == segments
    with pytest.raises(ValueError, match='Conflicting'):
        apply(before, [], '2026-01-01', '2026-01-02', OLD, segments)


@pytest.mark.parametrize('segments', [
    [['2026-01-01', '2026-01-03', OLD], ['2026-01-03', '2026-01-04', NEW]],
    [['2026-01-01', '2026-01-03', OLD], ['2026-01-04', '2026-01-05', OLD]],
    [['2025-12-31', '2026-01-03', OLD]],
    [['2026-01-01', '2026-01-03', '2026-10-23T01:00:00']],
])
def test_corrupt_version_proof_is_not_trusted(segments):
    with pytest.raises(ValueError):
        expand_versions(segments, 2026)


def test_bounded_worst_case_and_full_verification_compacts_versions():
    first = date(2026, 1, 1)
    segments = [[str(first + timedelta(days=i)), str(first + timedelta(days=i)), OLD if i % 2 else NEW]
                for i in range(365)]
    rows, versions, _ = apply([], [], '2026-01-01', '2026-12-31', LATEST, segments)
    assert rows == [] and versions == [['2026-01-01', '2026-12-31', LATEST]]
    assert contiguous_through(versions, 2026) == '2026-12-31'
