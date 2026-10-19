"""Maintenance entrypoints are checked only by the source release gate."""
import copy
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import assembly_contract as assembly


def bundles(entrypoint):
    publisher = SimpleNamespace(project_id='maintenance', job_key='maintenance-v1',
                                entrypoint=entrypoint)
    return (SimpleNamespace(id='sample', maintenance_publishers=(publisher,)),)


def test_source_entrypoint_is_checked_without_executing_its_code(tmp_path):
    path = tmp_path / 'scripts/import_example.py'
    path.parent.mkdir()
    path.write_text('raise AssertionError("maintenance code must never execute")\n', encoding='utf-8')
    assert not assembly.validate_maintenance_entrypoints(tmp_path, bundles('scripts/import_example.py'))


@pytest.mark.parametrize(('damage', 'expected'), [
    ('missing', 'missing/unreadable'), ('directory', 'not a file'), ('outside', 'outside root/scripts'),
])
def test_source_entrypoint_rejects_missing_directory_and_outside_paths(tmp_path, damage, expected):
    root = tmp_path / 'workspace'
    (root / 'scripts').mkdir(parents=True)
    entrypoint = 'scripts/import_example.py'
    if damage == 'directory':
        (root / entrypoint).mkdir()
    elif damage == 'outside':
        (tmp_path / 'outside.py').write_text('pass\n', encoding='utf-8')
        entrypoint = '../outside.py'
    failures = assembly.validate_maintenance_entrypoints(root, bundles(entrypoint))
    assert len(failures) == 1 and expected in failures[0]
    assert 'sample/maintenance/maintenance-v1' in failures[0]


@pytest.mark.parametrize('whole_scripts', [False, True])
def test_source_entrypoint_cannot_escape_through_a_link_or_junction(tmp_path, whole_scripts):
    root, outside = tmp_path / 'workspace', tmp_path / 'outside'
    root.mkdir()
    outside.mkdir()
    (outside / 'import_example.py').write_text('pass\n', encoding='utf-8')
    if whole_scripts:
        link, entrypoint = root / 'scripts', 'scripts/import_example.py'
    else:
        (root / 'scripts').mkdir()
        link, entrypoint = root / 'scripts/linked', 'scripts/linked/import_example.py'
    if os.name == 'nt':
        def literal(path):
            return "'" + str(path).replace("'", "''") + "'"
        command = ('New-Item -ItemType Junction -Path ' + literal(link)
                   + ' -Target ' + literal(outside) + ' | Out-Null')
        subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                       check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        link.symlink_to(outside, target_is_directory=True)
    failures = assembly.validate_maintenance_entrypoints(root, bundles(entrypoint))
    assert len(failures) == 1 and 'outside root/scripts' in failures[0]


def cli_inputs(tmp_path, monkeypatch):
    path = tmp_path / 'src/empire/features/news/query.py'
    path.parent.mkdir(parents=True)
    path.write_text('pass\n', encoding='utf-8')
    entrypoint = tmp_path / 'scripts/import_example.py'
    entrypoint.parent.mkdir()
    entrypoint.write_text('raise AssertionError("do not import")\n', encoding='utf-8')
    original = 'empire.plugins.data.news'
    target = 'empire.features.news.query'
    baseline = {'schema': 1, 'semantic': {}, 'bindings': {
        'plugins': {'data.news': {'module': original, 'qualname': 'NewsDataPlugin'}},
        'datasets': {}, 'pages': {}, 'tests': {},
    }}
    current = copy.deepcopy(baseline)
    current['bindings']['plugins']['data.news']['module'] = target
    order = {'schema': 1, **{key: ['first', 'second'] for key in assembly.ORDER_FIELDS}}
    values = {
        'baseline.json': baseline,
        'mapping.json': {'modules': {original: target}, 'test_paths': {}},
        'order.json': order,
    }
    for name, value in values.items():
        (tmp_path / name).write_text(json.dumps(value), encoding='utf-8')
    monkeypatch.setattr(assembly, '__file__', str(tmp_path / 'scripts/assembly_contract.py'))
    monkeypatch.setattr(assembly, 'snapshot', lambda root: current)
    monkeypatch.setattr(assembly, 'order_snapshot', lambda root: order)
    calls = []

    def source_gate(root):
        calls.append(root)
        return assembly.validate_maintenance_entrypoints(root, bundles('scripts/import_example.py'))

    monkeypatch.setattr(assembly, 'source_declaration_failures', source_gate)
    args = ['check', '--baseline', str(tmp_path / 'baseline.json'),
            '--mapping', str(tmp_path / 'mapping.json'), '--order-baseline', str(tmp_path / 'order.json')]
    return args, order, entrypoint, calls


@pytest.mark.parametrize(('damage', 'expected'), [
    ('none', 'PASS'), ('mapping', 'bindings.plugins.data.news.module'),
    ('order', 'order.startup'), ('entrypoint', 'missing/unreadable maintenance entrypoint'),
])
def test_check_cli_executes_exact_mapping_order_and_maintenance_checks(
        tmp_path, monkeypatch, capsys, damage, expected):
    args, order, entrypoint, calls = cli_inputs(tmp_path, monkeypatch)
    if damage == 'mapping':
        start = args.index('--mapping')
        del args[start:start + 2]
    elif damage == 'order':
        order['startup'].reverse()
    elif damage == 'entrypoint':
        entrypoint.unlink()
    assert assembly.main(args) == (0 if damage == 'none' else 1)
    assert calls == [tmp_path.resolve()]
    assert expected in capsys.readouterr().out


def test_check_cli_cannot_skip_source_check_by_omitting_optional_order_baseline(tmp_path, monkeypatch):
    args, _, entrypoint, calls = cli_inputs(tmp_path, monkeypatch)
    start = args.index('--order-baseline')
    del args[start:start + 2]
    entrypoint.unlink()
    assert assembly.main(args) == 1
    assert calls == [tmp_path.resolve()]


def test_builtin_source_gate_uses_maintenance_declarations_from_the_allowlist():
    root = Path(__file__).resolve().parents[1]
    assert not assembly.source_declaration_failures(root)
