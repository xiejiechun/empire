import copy

import pytest

from empire.features.yuanhang.contract import FINANCIAL_JOB, PRICE_JOB
from empire.sources.yuanhang_payload import digest
from scripts.migrate_yuanhang_checkpoint import rebind_scope

OLD = ['000001.SZ', '000002.SZ']
NEW = ['000002.SZ', '000003.SZ']


def cursor():
    return dict(contract=2, phase='collecting', maintenance_scope='recent', force_full=False,
                scope_hash=digest(OLD), batch_id='original-batch', pages=12, collected=120,
                next_index=1, skipped_units=0, next_year=1900, snapshot_hash='',
                through='2026-11-03', run_date='2026-11-03', deferred={})


@pytest.mark.parametrize('job', [PRICE_JOB, FINANCIAL_JOB])
def test_rebinding_preserves_batch_and_cutoff_but_never_reuses_old_position(job):
    old = cursor()
    before = copy.deepcopy(old)
    actual = rebind_scope(old, NEW, job, OLD)
    assert actual == {**before, 'scope_hash': digest(NEW), 'next_index': 0, 'skipped_units': 0}
    assert old == before
    assert rebind_scope(actual, NEW, job, OLD) == actual
    assert rebind_scope(old, OLD, job, OLD) == old


@pytest.mark.parametrize('change', [
    {'current_plan': {}}, {'current_plan': {'code': OLD[0]}}, {'snapshot_hash': 'partial'},
    {'next_year': 2026}, {'contract': 1}, {'phase': 'awaiting_archive'}, {'phase': 'complete'},
    {'maintenance_scope': 'backfill'}, {'force_full': True}, {'force_full': None},
    {'plans': {}}, {'work_codes': []}, {'round_end': 50}, {'replan_recent': True},
    {'pages': -1}, {'pages': True}, {'collected': -1}, {'next_index': -1},
    {'next_index': 15001}, {'skipped_units': 2}, {'through': '2026-02-30'},
    {'scope_hash': 'unknown'}, {'batch_id': ''},
])
def test_unsafe_or_malformed_checkpoint_is_rejected_without_mutation(change):
    old = {**cursor(), **change}
    before = copy.deepcopy(old)
    with pytest.raises(ValueError):
        rebind_scope(old, NEW, PRICE_JOB, OLD)
    assert old == before


@pytest.mark.parametrize('codes', [[], NEW[::-1], [NEW[0], NEW[0]], ['wrong']])
def test_invalid_scope_is_rejected(codes):
    with pytest.raises(ValueError):
        rebind_scope(cursor(), codes, PRICE_JOB)


@pytest.mark.parametrize('previous', [None, OLD[::-1], OLD[:1], NEW, OLD + [OLD[-1]]])
def test_unverified_previous_pool_cannot_authorize_position_mapping(previous):
    with pytest.raises(ValueError):
        rebind_scope(cursor(), NEW, FINANCIAL_JOB, previous)


def test_suffix_addition_keeps_position_without_replaying_confirmed_prefix():
    old = cursor()
    new = OLD + ['000003.SZ']
    assert rebind_scope(old, new, FINANCIAL_JOB, OLD) == {**old, 'scope_hash': digest(new)}


def test_new_stock_inside_completed_prefix_refuses_silent_skip_or_mass_replay():
    with pytest.raises(ValueError, match='interrupt the completed prefix'):
        rebind_scope(cursor(), ['000000.SZ', *OLD], FINANCIAL_JOB, OLD)
