import copy
import socket
from pathlib import Path

import pytest

from scripts.assembly_contract import compare, differences, snapshot

ROOT = Path(__file__).resolve().parents[1]


def test_snapshot_has_no_network_or_running_services(monkeypatch):
    from empire.core.manager import PluginManager

    def forbidden(*args, **kwargs):
        raise AssertionError('Declaration inspection must not connect or start services')

    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(PluginManager, 'start', forbidden)
    monkeypatch.setattr(PluginManager, 'autostart', forbidden)
    first = snapshot(ROOT)
    assert first == snapshot(ROOT)
    assert 'sina-news' in first['semantic']['tasks']
    assert 'news' in first['semantic']['pages']
    assert not compare(first, first, {}, ROOT)


@pytest.fixture
def declared():
    return snapshot(ROOT)


@pytest.mark.parametrize('group,key,field,value', [
    ('tasks', 'sina-news', 'interval_seconds', 99),
    ('plugins', 'data.news', 'requires', []),
    ('pages', 'news', 'cache_policy', 'persistent'),
])
def test_same_count_changed_semantics_fail(declared, group, key, field, value):
    changed = copy.deepcopy(declared)
    changed['semantic'][group][key][field] = value
    assert compare(declared, changed, {}, ROOT) == [f'semantic.{group}.{key}.{field}']


def test_namespace_and_schema_drift_cannot_be_hidden_by_mapping(declared):
    changed = copy.deepcopy(declared)
    namespace = next(iter(changed['semantic']['datasets']))
    changed['semantic']['datasets'][namespace]['schema_version'] += 1
    assert compare(declared, changed, {}, ROOT) == [f'semantic.datasets.{namespace}.schema_version']
    with pytest.raises(ValueError, match='Only explicit'):
        compare(declared, changed, {'semantic': {}}, ROOT)


def test_exact_module_mapping_does_not_rewrite_business_strings(declared):
    before = copy.deepcopy(declared)
    old = 'empire.legacy_news'
    new = before['bindings']['plugins']['data.news']['module']
    before['bindings']['plugins']['data.news']['module'] = old
    assert not compare(before, declared, {'modules': {old: new}}, ROOT)
    assert compare(before, declared, {}, ROOT) == ['bindings.plugins.data.news.module']
    with pytest.raises(ValueError, match='unused'):
        compare(before, declared, {'modules': {'unused': new}}, ROOT)


def test_differences_detect_same_count_replaced_identity():
    assert differences({'one': {'id': 'one'}}, {'two': {'id': 'two'}}) == ['one', 'two']
