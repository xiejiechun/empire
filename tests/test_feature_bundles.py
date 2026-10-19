"""Business ownership is checked before start; declaration order is explicit."""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from empire.bootstrap import build_manager
from empire.contracts.archive_version import ArchiveVersion
from empire.contracts.bundle import (
    FeatureBundle,
    MaintenancePublisher,
    OrderedContribution,
    ordered,
    positioned,
)
from empire.contracts.dataset import DatasetContribution
from empire.contracts.plugin import PluginManifest
from empire.contracts.task import TaskContribution
from empire.core.manager import DependencyError, PluginManager
from empire.features import builtin

CFG = {'redis': {}, 'mysql': {}, 'archive': {}, 'ingest': {}, 'rate_groups': {}}


class Publisher:
    def __init__(self, project, *, requires=()):
        self.project_id, self.job_key = project, project + '-v1'
        self.manifest = PluginManifest('collector.' + project, project,
                                      provides=('collector.' + project,), requires=requires)

    async def start(self, context):
        raise AssertionError('declaration assembly started a collector')

    async def stop(self):
        pass

    def health(self):
        return {}


def contribution(project, *, job=None, namespace=None, dataset=None):
    mapping = SimpleNamespace(DATASETS={dataset or project + '.page'},
        FINGERPRINT_NAMESPACE=namespace or project,
        FINGERPRINT_VERSION=ArchiveVersion(('utc',), observed_index=0))
    return DatasetContribution(mapping, 'incremental', {job or project + '-v1': project})


def feature(project, position=100):
    plugin = Publisher(project)
    return FeatureBundle(project,
        plugins=(OrderedContribution(position, plugin),),
        tasks=(OrderedContribution(position, TaskContribution(project, project, 'collector.' + project,
                                                             'sample', 'bounded sample')),),
        datasets=(OrderedContribution(position, contribution(project)),))


def assemble(monkeypatch, *bundles):
    monkeypatch.setattr(builtin, 'FACTORIES', tuple(lambda cfg, value=bundle: value for bundle in bundles))
    return build_manager(CFG)


def test_bundles_keep_individual_positions_even_if_allowlist_is_reversed(monkeypatch):
    first, second = feature('first'), feature('second', 200)
    # One bundle can contribute noncontiguous plugins around another business.
    extra = Publisher('extra')
    first = replace(first, plugins=(*first.plugins, OrderedContribution(300, extra)))
    left = assemble(monkeypatch, first, second)
    right = assemble(monkeypatch, second, first)
    assert list(left.entries) == list(right.entries)
    assert left.order == right.order
    assert list(left.entries)[:3] == ['collector.first', 'collector.second', 'collector.extra']
    assert list(left.entries['collection.control'].plugin.definitions) == ['first', 'second']
    assert [c.namespace for c in left.entries['dataset.astock'].plugin.contributions] == ['first', 'second']
    assert all(entry.context is None and entry.state == 'STOPPED' for entry in left.entries.values())
    assert not left.registry.values


def test_real_bundle_construction_reads_no_files_and_creates_no_widgets(monkeypatch):
    import builtins
    import io
    from pathlib import Path

    from PySide6.QtWidgets import QWidget

    # Complete normal module loading first; this guards declaration construction,
    # not Python's loader reading source files.
    expected = build_manager(CFG)

    def forbidden(*args, **kwargs):
        raise AssertionError('Declaration construction performed external I/O or created a page')

    with monkeypatch.context() as guard:
        guard.setattr(builtins, 'open', forbidden)
        guard.setattr(io, 'open', forbidden)
        guard.setattr(Path, 'read_text', forbidden)
        guard.setattr(Path, 'read_bytes', forbidden)
        guard.setattr(QWidget, '__init__', forbidden)
        actual = build_manager(CFG)
    assert list(actual.entries) == list(expected.entries)
    assert actual.order == expected.order
    assert all(entry.context is None and entry.state == 'STOPPED' for entry in actual.entries.values())
    assert not actual.registry.values


@pytest.mark.parametrize('domain', ('plugins', 'tasks', 'datasets'))
def test_equal_ordinals_never_use_whitelist_order_to_resolve_conflict(monkeypatch, domain):
    left, right = feature('left'), feature('right', 200)
    right = replace(right, **{domain: (replace(getattr(right, domain)[0], ordinal=100),)})
    with pytest.raises(ValueError, match='贡献顺序重复'):
        assemble(monkeypatch, left, right)


def test_order_values_are_integer_and_fixed_series_cannot_grow_silently():
    with pytest.raises(ValueError, match='正整数'):
        OrderedContribution(True, 'a')
    with pytest.raises(ValueError):
        positioned((100,), ('a', 'b'))
    assert ordered((('b', OrderedContribution(200, 'b')), ('a', OrderedContribution(100, 'a'))), 'sample') == ('a', 'b')


@pytest.mark.parametrize('change', ('unknown_project', 'wrong_job', 'other_bundle'))
def test_dataset_requires_exact_same_bundle_job_and_project(monkeypatch, change):
    left, right = feature('left'), feature('right', 200)
    if change == 'unknown_project':
        replacement = contribution('unknown')
    elif change == 'wrong_job':
        replacement = contribution('left', job='unknown-v1')
    else:
        replacement = contribution('right', namespace='wrong', dataset='wrong.page')
    left = replace(left, datasets=(OrderedContribution(100, replacement),))
    with pytest.raises(ValueError, match='数据归属不符'):
        assemble(monkeypatch, left, right)


def test_task_cannot_borrow_another_bundle_provider_or_disagree_with_publisher(monkeypatch):
    left, right = feature('left'), feature('right', 200)
    task = replace(left.tasks[0].value, capability='collector.right')
    with pytest.raises(ValueError, match='不属于本业务包'):
        assemble(monkeypatch, replace(left, tasks=(OrderedContribution(100, task),)), right)
    left.plugins[0].value.project_id = 'different'
    with pytest.raises(ValueError, match='发布者项目不符'):
        assemble(monkeypatch, left, right)


def test_explicit_maintenance_publisher_does_not_create_a_scheduled_task(monkeypatch):
    maint = MaintenancePublisher('bse-code-mapping', 'bse-code-mapping-v1', 'scripts/import_bse_code_mapping.py')
    bundle = FeatureBundle('aliases', datasets=(OrderedContribution(100, contribution('bse-code-mapping')),),
                           maintenance_publishers=(maint,))
    manager = assemble(monkeypatch, bundle)
    assert manager.entries['collection.control'].plugin.definitions == {}
    assert manager.entries['dataset.astock'].plugin.contributions[0].projects == {
        'bse-code-mapping-v1': 'bse-code-mapping'}
    assert all(entry.state == 'STOPPED' for entry in manager.entries.values())


@pytest.mark.parametrize('entrypoint', ('', '.', '../import.py', 'scripts/../import.py', 'scripts/import.txt',
                                      'C:/scripts/import.py'))
def test_maintenance_entrypoint_must_be_explicit_and_local(entrypoint):
    with pytest.raises(ValueError, match='入口'):
        MaintenancePublisher('maintenance', 'maintenance-v1', entrypoint)


def test_missing_wrong_duplicate_or_unused_maintenance_owner_is_rejected(monkeypatch):
    dataset = OrderedContribution(100, contribution('maintenance'))
    owner = MaintenancePublisher('maintenance', 'maintenance-v1', 'scripts/import_bse_code_mapping.py')
    with pytest.raises(ValueError, match='数据归属不符'):
        assemble(monkeypatch, FeatureBundle('sample', datasets=(dataset,)))
    with pytest.raises(ValueError, match='数据归属不符'):
        assemble(monkeypatch, FeatureBundle('sample', datasets=(dataset,),
            maintenance_publishers=(replace(owner, job_key='wrong-v1'),)))
    with pytest.raises(ValueError, match='发布者项目或 job 重复'):
        assemble(monkeypatch, FeatureBundle('sample', datasets=(dataset,), maintenance_publishers=(owner, owner)))
    with pytest.raises(ValueError, match='没有对应数据贡献'):
        assemble(monkeypatch, FeatureBundle('sample', maintenance_publishers=(owner,)))


@pytest.mark.parametrize('change', ('plugin', 'provider', 'task', 'dataset', 'namespace', 'missing', 'cycle'))
def test_existing_identity_and_dependency_guards_still_reject_before_start(monkeypatch, change):
    left, right = feature('left'), feature('right', 200)
    if change in ('plugin', 'provider'):
        attr = 'id' if change == 'plugin' else 'provides'
        right.plugins[0].value.manifest = replace(right.plugins[0].value.manifest,
                                                **{attr: getattr(left.plugins[0].value.manifest, attr)})
    elif change == 'task':
        right = replace(right, tasks=(OrderedContribution(200, left.tasks[0].value),))
    elif change in ('dataset', 'namespace'):
        replacement = contribution('right', dataset='left.page' if change == 'dataset' else 'right.page',
                                   namespace='left' if change == 'namespace' else 'right')
        right = replace(right, datasets=(OrderedContribution(200, replacement),))
    elif change == 'missing':
        left.plugins[0].value.manifest = replace(left.plugins[0].value.manifest, requires=('missing',))
    else:
        left.plugins[0].value.manifest = replace(left.plugins[0].value.manifest, requires=('collector.right',))
        right.plugins[0].value.manifest = replace(right.plugins[0].value.manifest, requires=('collector.left',))
    with pytest.raises((ValueError, DependencyError)):
        assemble(monkeypatch, left, right)


def test_one_publisher_can_own_multiple_datasets(monkeypatch):
    bundle = feature('sample')
    second = contribution('sample', namespace='sample-second', dataset='sample.second')
    bundle = replace(bundle, datasets=(*bundle.datasets, OrderedContribution(200, second)))
    manager = assemble(monkeypatch, bundle)
    assert set(manager.entries['dataset.astock'].plugin.datasets) == {'sample.page', 'sample.second'}


async def test_start_order_preserves_optional_provider_visibility():
    seen = []

    class Service(Publisher):
        async def start(self, context):
            if self.project_id == 'observer':
                seen.append(context.optional('collector.provider') is not None)
            return {self.manifest.provides[0]: self}

    for provider_order, observer_order in ((100, 200), (200, 100)):
        plugins = ordered((('sample', OrderedContribution(observer_order, Service('observer'))),
                           ('sample', OrderedContribution(provider_order, Service('provider')))), 'plugins')
        manager = PluginManager(list(plugins))
        for entry in manager.entries.values():
            entry.enabled = True
        await manager.autostart()
        await manager.shutdown()
    assert seen == [True, False]
