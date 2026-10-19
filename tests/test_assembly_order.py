import copy
import json
import socket
from pathlib import Path

import pytest

from scripts.assembly_contract import ORDER_FIELDS, compare_order, order_snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_order_snapshot_is_declaration_only_and_matches_pre_migration_baseline(monkeypatch):
    from empire.core.manager import PluginManager

    def forbidden(*args, **kwargs):
        raise AssertionError('Order inspection must not start services or connect')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(PluginManager, 'start', forbidden)
    monkeypatch.setattr(PluginManager, 'autostart', forbidden)
    current = order_snapshot(ROOT)
    baseline = json.loads((ROOT / 'docs/evidence/assembly-order-baseline-2026-10-19.json').read_text('utf8'))
    assert current == order_snapshot(ROOT)
    assert not compare_order(baseline, current)


@pytest.mark.parametrize('key', ORDER_FIELDS)
def test_same_count_reordering_is_not_hidden_by_semantic_sorting(key):
    before = {**{name: ['a', 'b'] for name in ORDER_FIELDS}, 'schema': 1}
    after = copy.deepcopy(before)
    after[key].reverse()
    assert compare_order(before, after) == ['order.' + key]


@pytest.mark.parametrize('damage', ['missing', 'duplicate', 'unknown', 'invalid_item', 'schema'])
def test_order_baseline_cannot_disable_comparison(damage):
    before = {**{name: ['a', 'b'] for name in ORDER_FIELDS}, 'schema': 1}
    after = copy.deepcopy(before)
    if damage == 'missing':
        del after['tasks']
    elif damage == 'duplicate':
        after['tasks'] = ['a', 'a']
    elif damage == 'unknown':
        after['allowed_reorder'] = True
    elif damage == 'invalid_item':
        after['tasks'] = [None]
    else:
        after['schema'] = 2
    with pytest.raises(ValueError, match='Invalid ordered'):
        compare_order(before, after)
