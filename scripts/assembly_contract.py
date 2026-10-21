"""Compare declared runtime identities without starting services or constructing pages."""
from __future__ import annotations

import argparse
import dataclasses
import json
import tomllib
from functools import partial
from pathlib import Path
from types import ModuleType


def plain(value):
    if dataclasses.is_dataclass(value):
        return {field.name: plain(getattr(value, field.name))
                for field in dataclasses.fields(value)}
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(plain(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f'Unsupported declaration value: {type(value).__name__}')


def symbol(value):
    if isinstance(value, partial):
        return {**symbol(value.func), 'args': plain(value.args), 'kwargs': plain(value.keywords)}
    if isinstance(value, ModuleType):
        return {'module': value.__name__, 'qualname': ''}
    if not isinstance(value, type) and not callable(value):
        value = type(value)
    return {'module': value.__module__, 'qualname': value.__qualname__}


def snapshot(root: Path):
    from empire.bootstrap import build_manager
    from empire.plugins.ui.plugin import UiPlugin

    cfg = tomllib.loads((root / 'config/app.example.toml').read_text(encoding='utf-8'))
    manager = build_manager(cfg)
    semantic = {'plugins': {}, 'tasks': {}, 'datasets': {}, 'pages': {}, 'preparation': {}}
    bindings = {'plugins': {}, 'datasets': {}, 'pages': {}, 'tests': {}}
    for ident, entry in sorted(manager.entries.items()):
        plugin = entry.plugin
        semantic['plugins'][ident] = plain(plugin.manifest)
        bindings['plugins'][ident] = symbol(plugin)
        for task_id, task in getattr(plugin, 'definitions', {}).items():
            if task_id in semantic['tasks']:
                raise ValueError(f'Duplicate task: {task_id}')
            semantic['tasks'][task_id] = plain(task)
        if isinstance(plugin, UiPlugin):
            for page in plugin.create_pages():
                if page.id in semantic['pages']:
                    raise ValueError(f'Duplicate page: {page.id}')
                semantic['pages'][page.id] = {
                    field.name: plain(getattr(page, field.name))
                    for field in dataclasses.fields(page) if field.name != 'factory'
                }
                bindings['pages'][page.id] = symbol(page.factory)
        for contribution in getattr(plugin, 'preparation', ()):
            key = ident + ':' + contribution.requirement
            if key in semantic['preparation']:
                raise ValueError(f'Duplicate preparation contribution: {key}')
            fields = plain(contribution)
            tests = {name: fields.pop(name) for name in tuple(fields) if name.endswith('_tests')}
            semantic['preparation'][key] = fields
            bindings['tests'][key] = tests
    catalog = manager.entries['dataset.astock'].plugin
    for contribution in catalog.contributions:
        key = contribution.namespace
        if key in semantic['datasets']:
            raise ValueError(f'Duplicate fingerprint namespace: {key}')
        semantic['datasets'][key] = {
            'datasets': plain(contribution.datasets), 'mode': contribution.mode,
            'projects': plain(contribution.projects), 'stale_outcome': contribution.stale_outcome,
            'schema_version': contribution.schema_version, 'fingerprint_version': plain(contribution.version),
        }
        bindings['datasets'][key] = symbol(contribution.mapping)
    if manager.registry.values or any(entry.context or entry.state != 'STOPPED'
                                      for entry in manager.entries.values()):
        raise RuntimeError('Declaration collection unexpectedly started a plugin')
    return {'schema': 1, 'semantic': plain(semantic), 'bindings': plain(bindings)}


def differences(before, after, prefix=''):
    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            path = f'{prefix}.{key}' if prefix else key
            if key not in before or key not in after:
                result.append(path)
            else:
                result.extend(differences(before[key], after[key], path))
        return result
    return [] if before == after else [prefix]


def compare(baseline, current, migration, root: Path, features=None):
    if baseline.get('schema') != 1 or current.get('schema') != 1:
        raise ValueError('Unsupported assembly snapshot schema')
    modules = migration.get('modules', {})
    test_paths = migration.get('test_paths', {})
    if set(migration) - {'modules', 'test_paths'}:
        raise ValueError('Only explicit module and test path mappings are allowed')
    for mapping in (modules, test_paths):
        if not isinstance(mapping, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                               for k, v in mapping.items()):
            raise ValueError('Migration mappings must contain exact string pairs')
    expected = json.loads(json.dumps(baseline['bindings']))
    used_modules, used_tests = set(), set()
    for group in ('plugins', 'datasets', 'pages'):
        for binding in expected[group].values():
            old = binding['module']
            if old in modules:
                binding['module'] = modules[old]
                used_modules.add(old)
    for groups in expected['tests'].values():
        for name, paths in groups.items():
            groups[name] = [test_paths.get(path, path) for path in paths]
            used_tests.update(path for path in paths if path in test_paths)
    if used_modules != set(modules) or used_tests != set(test_paths):
        raise ValueError('Migration includes unused mappings')
    failures = differences(baseline['semantic'], current['semantic'], 'semantic')
    if features is not None:
        if not isinstance(features, list):
            raise ValueError('Feature changes must be an explicit list')
        seen = set()
        for change in features:
            if not isinstance(change, dict) or set(change) != {'path', 'before', 'after', 'design', 'tests'}:
                raise ValueError('Feature change requires exact before/after and independent design/tests')
            path = change['path']
            parts = path.split('.')
            if (len(parts) != 5 or parts[:2] != ['semantic', 'preparation']
                    or parts[-1] not in ('scoped', 'cache_revision') or path in seen):
                raise ValueError('Only explicit preparation scope/cache feature changes are supported')
            seen.add(path)
            identity = '.'.join(parts[2:-1])
            old = baseline['semantic']['preparation'][identity][parts[-1]]
            new = current['semantic']['preparation'][identity][parts[-1]]
            if (type(old) is not type(change['before']) or type(new) is not type(change['after'])
                    or old != change['before'] or new != change['after'] or old == new):
                raise ValueError('Feature change is stale or does not match the exact semantic difference')
            if (not isinstance(change['tests'], list) or not change['tests'] or
                    any(not isinstance(p, str) or not (root / p).resolve().is_relative_to(root.resolve())
                        or not (root / p).is_file() for p in [change['design'], *change['tests']])):
                raise ValueError('Feature change design and tests must exist inside the repository')
            failures.remove(path)
    failures += differences(expected, current['bindings'], 'bindings')
    for group in ('plugins', 'datasets', 'pages'):
        for binding in current['bindings'][group].values():
            path = root / 'src' / Path(*binding['module'].split('.'))
            if not path.with_suffix('.py').is_file() and not (path / '__init__.py').is_file():
                failures.append('missing module: ' + binding['module'])
    for groups in current['bindings']['tests'].values():
        for paths in groups.values():
            for path in paths:
                resolved = (root / path).resolve()
                if not resolved.is_relative_to(root.resolve()) or not resolved.is_file():
                    failures.append('missing/outside test: ' + path)
    return failures



ORDER_FIELDS = ('plugins', 'startup', 'tasks', 'datasets', 'pages', 'preparation')


def order_snapshot(root: Path):
    """Capture order separately so the original semantic baseline stays immutable."""
    from empire.bootstrap import build_manager
    from empire.plugins.ui.plugin import UiPlugin

    cfg = tomllib.loads((root / 'config/app.example.toml').read_text(encoding='utf-8'))
    manager = build_manager(cfg)
    result = {
        'schema': 1,
        'plugins': list(manager.entries),
        'startup': list(manager.order),
        'tasks': list(manager.entries['collection.control'].plugin.definitions),
        'datasets': [c.namespace for c in manager.entries['dataset.astock'].plugin.contributions],
        'pages': [page.id for entry in manager.entries.values()
                  if isinstance(entry.plugin, UiPlugin) for page in entry.plugin.create_pages()],
        'preparation': [ident + ':' + item.requirement
                        for ident, entry in manager.entries.items()
                        for item in getattr(entry.plugin, 'preparation', ())],
    }
    if manager.registry.values or any(entry.context or entry.state != 'STOPPED'
                                      for entry in manager.entries.values()):
        raise RuntimeError('Order inspection unexpectedly started a plugin')
    return result


def compare_order(baseline, current):
    for value in (baseline, current):
        if (value.get('schema') != 1
                or set(value) - {'schema', 'origin_commit', *ORDER_FIELDS}
                or any(not isinstance(value.get(key), list)
                       or any(not isinstance(item, str) for item in value[key])
                       or len(value[key]) != len(set(value[key])) for key in ORDER_FIELDS)):
            raise ValueError('Invalid ordered assembly snapshot')
    return ['order.' + key for key in ORDER_FIELDS if baseline[key] != current[key]]


def validate_maintenance_entrypoints(root: Path, bundles):
    """Source gate only; packaged runtime assembly must not inspect scripts."""
    root = root.resolve()
    scripts = root / 'scripts'
    failures = []
    for bundle in bundles:
        for publisher in bundle.maintenance_publishers:
            identity = f'{bundle.id}/{publisher.project_id}/{publisher.job_key}'
            label = identity + ': ' + publisher.entrypoint
            try:
                resolved = (root / publisher.entrypoint).resolve(strict=True)
                if not resolved.is_relative_to(scripts):
                    failures.append('maintenance entrypoint outside root/scripts: ' + label)
                elif not resolved.is_file():
                    failures.append('maintenance entrypoint is not a file: ' + label)
            except (OSError, RuntimeError):
                failures.append('missing/unreadable maintenance entrypoint: ' + label)
    return failures


def source_declaration_failures(root: Path):
    """Inspect the explicit builtin declarations without importing maintenance code."""
    from empire.features.builtin import builtin_bundles

    cfg = tomllib.loads((root / 'config/app.example.toml').read_text(encoding='utf-8'))
    return validate_maintenance_entrypoints(root, builtin_bundles(cfg))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'check'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--mapping', type=Path)
    parser.add_argument('--order-baseline', type=Path)
    parser.add_argument('--feature-changes', type=Path)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    current = snapshot(root)
    if args.action == 'snapshot':
        if args.output is None:
            parser.error('snapshot requires --output')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n',
                               encoding='utf-8')
        print('Assembly declaration snapshot saved; no plugin was started')
        return 0
    if args.baseline is None:
        parser.error('check requires --baseline')
    baseline = json.loads(args.baseline.read_text(encoding='utf-8'))
    migration = json.loads(args.mapping.read_text(encoding='utf-8')) if args.mapping else {}
    features = json.loads(args.feature_changes.read_text(encoding='utf-8')) if args.feature_changes else None
    failures = compare(baseline, current, migration, root, features)
    failures += source_declaration_failures(root)
    if args.order_baseline:
        ordered = json.loads(args.order_baseline.read_text(encoding='utf-8'))
        failures += compare_order(ordered, order_snapshot(root))
    if failures:
        print('FAIL assembly contract: ' + ', '.join(failures[:30]))
        return 1
    print('PASS exact assembly identities, semantics and mapped implementation/test locations')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
