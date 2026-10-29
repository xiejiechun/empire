import copy
import json
from pathlib import Path

import pytest

from scripts.assembly_contract import compare, compare_order, order_snapshot, snapshot

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module', params=['additive.themes', 'service.yuanhang_service', 'management.identities',
                                      'computation.market_review', 'additive.margin'])
def added(request):
    changes = json.loads((ROOT / 'docs/assembly-feature-changes.json').read_text('utf-8'))
    addition = next(c for c in changes if c['path'] == request.param)
    current, order = snapshot(ROOT), order_snapshot(ROOT)
    before, old_order = copy.deepcopy(current), copy.deepcopy(order)
    for domain in ('semantic', 'bindings'):
        for group, items in addition['after'][domain].items():
            for identity in items:
                del before[domain][group][identity]
    for group, items in addition['after']['order'].items():
        old_order[group] = [v for v in old_order[group] if v not in items]
    return before, current, old_order, order, addition


def test_exact_new_feature_preserves_old_baselines_and_order(added):
    before, current, old_order, order, change = added
    assert not compare(before, current, {}, ROOT, [change])
    assert not compare_order(old_order, order, [change])
    assert compare(before, current, {}, ROOT)
    assert compare_order(old_order, order)


def test_existing_identity_cannot_be_overwritten_as_addition(added):
    before, current, _, _, change = added
    baseline = copy.deepcopy(before)
    identity = next(iter(change['after']['semantic']['plugins']))
    baseline['semantic']['plugins'][identity] = {'old': True}
    with pytest.raises(ValueError, match='existing'):
        compare(baseline, current, {}, ROOT, [change])


def test_reviewed_addition_does_not_hide_semantic_drift_or_other_owner(added):
    before, current, _, _, change = added
    drift = copy.deepcopy(current)
    identity = next(iter(change['after']['semantic']['plugins']))
    drift['semantic']['plugins'][identity]['autostart'] = False
    with pytest.raises(ValueError, match='reviewed'):
        compare(before, drift, {}, ROOT, [change])
    wrong = copy.deepcopy(change)
    wrong['after']['bindings']['plugins'][identity]['module'] = 'empire.features.stocks.query'
    with pytest.raises(ValueError, match='owner'):
        compare(before, current, {}, ROOT, [wrong])


def test_order_change_or_undeclared_addition_still_fails(added):
    _, _, old, current, change = added
    drift = copy.deepcopy(current)
    drift['tasks'][0], drift['tasks'][1] = drift['tasks'][1], drift['tasks'][0]
    assert 'order.tasks' in compare_order(old, drift, [change])
    drift = copy.deepcopy(current)
    drift['plugins'].append('ui.undeclared')
    assert 'order.plugins' in compare_order(old, drift, [change])


def test_missing_design_and_duplicate_feature_are_rejected(added):
    before, current, _, _, change = added
    wrong = copy.deepcopy(change)
    wrong['design'] = '../unreviewed.md'
    with pytest.raises(ValueError, match='design'):
        compare(before, current, {}, ROOT, [wrong])
    with pytest.raises(ValueError, match='Duplicate'):
        compare(before, current, {}, ROOT, [change, change])


def test_source_service_cannot_declare_business_or_non_source_plugins():
    from scripts.assembly_additions import validate

    changes = json.loads((ROOT / 'docs/assembly-feature-changes.json').read_text('utf-8'))
    change = next(c for c in changes if c['path'] == 'service.yuanhang_service')
    wrong = copy.deepcopy(change)
    wrong['after']['semantic']['tasks']['fake-market-task'] = {}
    with pytest.raises(ValueError, match='only plugins'):
        validate(wrong)
    wrong = copy.deepcopy(change)
    for group in ('semantic', 'bindings'):
        plugin = wrong['after'][group]['plugins'].pop('source.yuanhang_identity')
        wrong['after'][group]['plugins']['collector.disguised'] = plugin
    for group in ('plugins', 'startup'):
        wrong['after']['order'][group] = ['collector.disguised']
    with pytest.raises(ValueError, match='source plugin'):
        validate(wrong)


@pytest.mark.parametrize('group', ['plugins', 'tasks', 'datasets'])
def test_preview_only_collector_still_requires_business_groups(group):
    from scripts.assembly_additions import validate
    changes = json.loads((ROOT / 'docs/assembly-feature-changes.json').read_text('utf8'))
    change = copy.deepcopy(next(c for c in changes if c['path'] == 'additive.margin'))
    assert not change['after']['semantic']['pages']
    validate(change)
    change['after']['semantic'][group] = {}
    with pytest.raises(ValueError, match='exact identities'):
        validate(change)


def test_all_additions_preserve_frozen_global_order_together():
    changes = json.loads((ROOT / 'docs/assembly-feature-changes.json').read_text('utf-8'))
    baseline = json.loads((ROOT / 'docs/evidence/assembly-order-baseline-2026-10-19.json').read_text('utf-8'))
    assert not compare_order(baseline, order_snapshot(ROOT), changes)


def test_computation_addition_cannot_register_collectors_or_datasets():
    from scripts.assembly_additions import validate
    changes = json.loads((ROOT / 'docs/assembly-feature-changes.json').read_text('utf-8'))
    change = copy.deepcopy(next(c for c in changes if c['path'] == 'computation.market_review'))
    change['after']['semantic']['datasets']['unexpected'] = {}
    with pytest.raises(ValueError, match='Computation'):
        validate(change)
    change['after']['semantic']['datasets'].clear()
    change['after']['semantic']['plugins']['collector.market_review'] = change['after']['semantic']['plugins'].pop('data.market_review')
    change['after']['order']['plugins'] = list(change['after']['semantic']['plugins'])
    change['after']['order']['startup'] = change['after']['order']['plugins']
    change['after']['bindings']['plugins']['collector.market_review'] = change['after']['bindings']['plugins'].pop('data.market_review')
    with pytest.raises(ValueError, match='query/UI'):
        validate(change)


def test_management_additions_cannot_disguise_collectors_or_other_modules():
    from scripts.assembly_additions import validate

    changes = json.loads((ROOT / 'docs/assembly-feature-changes.json').read_text('utf-8'))
    change = next(c for c in changes if c['path'] == 'management.identities')
    wrong = copy.deepcopy(change)
    wrong['after']['semantic']['tasks']['hidden-collector'] = {}
    with pytest.raises(ValueError, match='plugins/pages only'):
        validate(wrong)
    wrong = copy.deepcopy(change)
    wrong['after']['bindings']['pages']['identities']['module'] = 'empire.features.stocks.ui'
    with pytest.raises(ValueError, match='another owner'):
        validate(wrong)


def test_additive_collection_preparation_requires_exact_provider_and_tests():
    changes = json.loads((ROOT / 'docs/assembly-feature-changes.json').read_text('utf8'))
    additions = [c for c in changes if c['path'].startswith('semantic.preparation.data.yuanhang_limits:')]
    current = snapshot(ROOT)
    before = copy.deepcopy(current)
    for change in additions:
        identity = change['path'].removeprefix('semantic.preparation.')
        del before['semantic']['preparation'][identity]
        del before['bindings']['tests'][identity]
    assert len(additions) == 6
    assert not compare(before, current, {}, ROOT, additions)
    for field, bad in [('capability', 'stocks.query'), ('source_tests', []), ('collector', 'collector.unregistered')]:
        wrong = copy.deepcopy(additions)
        wrong[0]['after'][field] = bad
        with pytest.raises(ValueError):
            compare(before, current, {}, ROOT, wrong)
