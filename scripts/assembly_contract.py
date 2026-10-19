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


def compare(baseline, current, migration, root: Path):
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('snapshot', 'check'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--mapping', type=Path)
    args = parser.parse_args()
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
    failures = compare(baseline, current, migration, root)
    if failures:
        print('FAIL assembly contract: ' + ', '.join(failures[:30]))
        return 1
    print('PASS exact assembly identities, semantics and mapped implementation/test locations')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
