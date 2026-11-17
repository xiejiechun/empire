from copy import deepcopy

import pytest

from empire.features.margin.contract import digest
from scripts.migrate_margin_checkpoint import rebind_scope

OLD = ['600000.SH', '688256.SH']


def cursor(**changes):
    return dict(phase='fetch', contract=1, scope_hash=digest(OLD), batch_id='a'*32,
                index=1, pages=1, collected=2, securities=2, through='2026-11-11', **changes)


def test_added_tail_keeps_original_batch_and_only_remaining_securities():
    before = cursor()
    new = OLD + ['920067.BJ']
    actual = rebind_scope(before, new, OLD)
    assert actual == {**before, 'scope_hash': digest(new), 'securities': 3}
    assert rebind_scope(actual, new, OLD) == actual
    assert before == cursor()


def test_removed_completed_security_maps_prefix_without_replaying():
    before = cursor()
    new = ['688256.SH', '920067.BJ']
    assert rebind_scope(before, new, OLD) == {**before, 'scope_hash': digest(new), 'index': 0}


def test_removed_all_remaining_still_requires_whole_round_archive_confirmation():
    result = rebind_scope(cursor(), OLD[:1], OLD)
    assert result['phase'] == 'awaiting_archive' and result['pages'] == result['index'] == 1


def test_added_security_inside_completed_prefix_cannot_skip_or_replay():
    with pytest.raises(ValueError, match='穿插'):
        rebind_scope(cursor(), ['000001.SZ', *OLD], OLD)


@pytest.mark.parametrize('change', [
    {'phase': 'complete'}, {'phase': 'awaiting_archive'}, {'contract': 2}, {'index': -1},
    {'index': True}, {'index': 2}, {'pages': 0}, {'pages': 30001}, {'collected': -1},
    {'batch_id': ''}, {'through': '2026-02-30'}, {'securities': 3}, {'scope_hash': 'bad'}, {'extra': True},
])
def test_invalid_checkpoint_is_rejected(change):
    before = {**cursor(), **change}
    saved = deepcopy(before)
    with pytest.raises((ValueError, TypeError)):
        rebind_scope(before, OLD + ['920067.BJ'], OLD)
    assert saved == before


@pytest.mark.parametrize('bad', [[], list(reversed(OLD)), OLD + [OLD[0]], ['600000'], [None], '600000.SH'])
def test_invalid_previous_or_current_pool_is_rejected(bad):
    with pytest.raises((ValueError, TypeError)):
        rebind_scope(cursor(), bad, OLD)
    with pytest.raises((ValueError, TypeError)):
        rebind_scope(cursor(), OLD + ['920067.BJ'], bad)
