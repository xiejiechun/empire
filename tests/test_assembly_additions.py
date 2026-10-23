import copy
import json
from pathlib import Path

import pytest

from scripts.assembly_contract import compare, compare_order, order_snapshot, snapshot

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def added():
    changes = json.loads((ROOT / 'docs/assembly-feature-changes.json').read_text('utf-8'))
    addition = next(c for c in changes if c['path'] == 'additive.themes')
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
    baseline['semantic']['plugins']['data.themes'] = {'old': True}
    with pytest.raises(ValueError, match='existing'):
        compare(baseline, current, {}, ROOT, [change])


def test_reviewed_addition_does_not_hide_semantic_drift_or_other_owner(added):
    before, current, _, _, change = added
    drift = copy.deepcopy(current)
    drift['semantic']['tasks']['kaipanla-themes']['interval_seconds'] = 1
    with pytest.raises(ValueError, match='reviewed'):
        compare(before, drift, {}, ROOT, [change])
    wrong = copy.deepcopy(change)
    wrong['after']['bindings']['plugins']['data.themes']['module'] = 'empire.features.stocks.query'
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
