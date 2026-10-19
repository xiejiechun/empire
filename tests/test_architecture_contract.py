"""Counterexamples for the offline import boundary and decreasing debt contract."""
import json
from pathlib import Path

import pytest

from scripts.architecture_contract import analyze, import_edges, main, read_modules


@pytest.fixture
def project(tmp_path):
    policy = dict(schema=1, owners={
        'news': {'kind': 'business'}, 'holders': {'kind': 'business'},
        'application': {'kind': 'platform'},
    }, module_groups=[], feature_layouts=[], debt=[])

    def write(module, code='', *, owner='news', role='query', package=False, **kwargs):
        target = tmp_path / 'src' / Path(*module.split('.'))
        target = target / '__init__.py' if package else target.with_suffix('.py')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(code, 'utf-8')
        if not any(module in group['modules'] for group in policy['module_groups']):
            policy['module_groups'].append(dict(owner=owner, role=role, reason='Test responsibility',
                                               modules=[module], **kwargs))
        return target

    return tmp_path, policy, write


def baseline(root, policy):
    report = analyze(root, policy)
    assert not report['errors']
    policy['debt'] = report['new_debt']
    assert analyze(root, policy)['passed']


def test_checker_never_imports_application_code(project):
    root, policy, write = project
    marker = root / 'executed.txt'
    write('empire.feature', f"open({str(marker)!r}, 'w').write('unsafe')\nraise RuntimeError('executed')\n")
    assert analyze(root, policy)['passed']
    assert not marker.exists()


def test_absolute_relative_and_from_package_imports_resolve_identically(project):
    root, policy, write = project
    write('empire.news', package=True, role='package')
    write('empire.news.api', 'VALUE = 1', role='contract')
    write('empire.news.page', 'from .api import VALUE\nfrom . import api\nimport empire.news.api as a\n')
    edges, errors = import_edges(read_modules(root))
    assert not errors
    assert len(edges) == 3
    assert {edge.target for edge in edges} == {'empire.news.api'}
    assert analyze(root, policy)['passed']


def test_relative_import_from_package_init_uses_its_own_package(project):
    root, policy, write = project
    write('empire.news', 'from .api import VALUE\n', package=True, role='package')
    write('empire.news.api', 'VALUE = 1', role='contract')
    edges, errors = import_edges(read_modules(root))
    assert not errors and edges[0].target == 'empire.news.api'


@pytest.mark.parametrize('role', ['query', 'ui', 'shared_ui', 'dataset', 'diagnostic'])
def test_collector_moved_outside_collectors_directory_still_fails(project, role):
    root, policy, write = project
    write('empire.contracts.innocent_name', 'def fetch(): pass', role='collector')
    write('empire.reader', 'from empire.contracts.innocent_name import fetch\n', role=role)
    report = analyze(root, policy)
    assert not report['passed']
    assert [item['rule'] for item in report['new_debt']] == ['reader_to_execution']


def test_pure_source_contract_is_debt_but_not_mislabeled_as_execution(project):
    root, policy, write = project
    write('empire.plugins.collectors.kinds', 'KINDS = ()', role='contract',
          legacy_collector_location=True)
    write('empire.query', 'from empire.plugins.collectors.kinds import KINDS\n')
    assert [x['rule'] for x in analyze(root, policy)['new_debt']] == ['misplaced_source_contract']


def test_debt_can_shrink_but_new_symbol_cannot_use_old_exception(project):
    root, policy, write = project
    write('empire.collector', 'a = b = c = 1', role='collector')
    query = write('empire.query', 'from empire.collector import a, b\n')
    baseline(root, policy)
    query.write_text('from empire.collector import a\n', 'utf-8')
    reduced = analyze(root, policy)
    assert reduced['passed'] and reduced['retired_debt'][0]['names'] == ['b']
    query.write_text('from empire.collector import a, c\n', 'utf-8')
    added = analyze(root, policy)
    assert not added['passed'] and added['new_debt'][0]['names'] == ['c']
    query.write_text('', 'utf-8')
    assert analyze(root, policy)['passed']


def test_splitting_existing_import_does_not_create_new_debt(project):
    root, policy, write = project
    write('empire.collector', role='collector')
    query = write('empire.query', 'from empire.collector import a, b\n')
    baseline(root, policy)
    query.write_text('from empire.collector import b\nfrom empire.collector import a\n', 'utf-8')
    assert analyze(root, policy)['passed']


def test_private_business_implementation_requires_exact_debt(project):
    root, policy, write = project
    write('empire.holders.query', 'def read(): pass', owner='holders')
    write('empire.news.query', 'from empire.holders.query import read\n')
    report = analyze(root, policy)
    assert [x['rule'] for x in report['new_debt']] == ['cross_business_private']
    baseline(root, policy)


def test_public_symbols_do_not_make_the_whole_helper_public(project):
    root, policy, write = project
    write('empire.holders.helper', 'read = internal = 1', owner='holders', public_symbols=['read'])
    caller = write('empire.news.query', 'from empire.holders.helper import read\n')
    assert analyze(root, policy)['passed']
    caller.write_text('from empire.holders.helper import internal\n', 'utf-8')
    assert not analyze(root, policy)['passed']


def test_private_symbol_remains_private_even_in_public_contract(project):
    root, policy, write = project
    write('empire.holders.contract', '_private = 1', owner='holders', role='contract')
    write('empire.news.query', 'from empire.holders.contract import _private\n')
    assert not analyze(root, policy)['passed']


def test_package_reexport_cannot_bypass_cross_business_privacy(project):
    root, policy, write = project
    write('empire.holders.internal', 'secret = 1', owner='holders')
    write('empire.news', 'from empire.holders.internal import secret\n', package=True, role='package')
    assert not analyze(root, policy)['passed']


def test_new_cycle_edge_is_rejected_even_inside_an_existing_cycle(project):
    root, policy, write = project
    first = write('empire.a', 'import empire.b\n')
    write('empire.b', 'import empire.c\n')
    write('empire.c', 'import empire.a\n')
    baseline(root, policy)
    first.write_text('import empire.b\nimport empire.c\n', 'utf-8')
    report = analyze(root, policy)
    assert report['cycles'] == [['empire.a', 'empire.b', 'empire.c']]
    assert len(report['new_debt']) == 1
    assert report['new_debt'][0]['target'] == 'empire.c'
    first.write_text('', 'utf-8')
    assert analyze(root, policy)['passed']


def test_type_only_and_function_local_imports_are_included(project):
    root, policy, write = project
    write('empire.collector', role='collector')
    write('empire.query', 'from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n'
          '    from empire.collector import Type\ndef f():\n    from empire.collector import fetch\n')
    report = analyze(root, policy)
    assert report['new_debt'][0]['names'] == ['Type', 'fetch']


@pytest.mark.parametrize('call', [
    "import importlib\nimportlib.import_module('empire.worker')",
    "import importlib as loader\nloader.import_module(name='empire.worker')",
    "from importlib import import_module as load\nload('empire.worker')",
    "__import__('empire.worker')",
    "import builtins as b\nb.__import__('empire.worker')",
    "from builtins import __import__ as load\nload('empire.worker')",
])
def test_literal_dynamic_internal_import_uses_same_boundary(project, call):
    root, policy, write = project
    write('empire.worker', role='collector')
    write('empire.query', call)
    assert analyze(root, policy)['new_debt'][0]['rule'] == 'reader_to_execution'


@pytest.mark.parametrize('call', [
    'import importlib\nimportlib.import_module(module_name)',
    "import importlib\nimportlib.import_module('.worker', 'empire')",
])
def test_unresolved_dynamic_import_fails_explicitly(project, call):
    root, policy, write = project
    write('empire.query', call)
    report = analyze(root, policy)
    assert not report['passed'] and 'dynamic import' in report['errors'][0]


def test_external_literal_dynamic_import_is_outside_internal_graph(project):
    root, policy, write = project
    write('empire.query', "import importlib\nimportlib.import_module('json')")
    assert analyze(root, policy)['passed']


def test_dynamic_fromlist_cannot_hide_an_internal_submodule(project):
    root, policy, write = project
    write('empire', package=True, role='package')
    write('empire.query', "__import__('empire', fromlist=['worker'])")
    report = analyze(root, policy)
    assert not report['passed']
    assert 'fromlist/context/level' in report['errors'][0]


def test_unknown_module_and_wildcard_imports_fail(project):
    root, policy, write = project
    write('empire.query', 'from empire.missing import *\n')
    errors = analyze(root, policy)['errors']
    assert any('unknown internal module' in text for text in errors)
    assert any('wildcard internal import' in text for text in errors)


def test_feature_layout_supports_future_news_and_holders_locations(project):
    root, policy, write = project
    write('empire.features.news.query', 'from ..holders.contract import VALUE\n')
    write('empire.features.holders.contract', 'VALUE = 1', owner='holders', role='contract')
    policy['module_groups'] = []
    policy['feature_layouts'] = [dict(prefix='empire.features.' + owner, owner=owner,
                                    reason='Business package', roles={'query': 'query', 'contract': 'contract'})
                                 for owner in ('news', 'holders')]
    assert analyze(root, policy)['passed']
    write('empire.features.news.unclassified', '')
    policy['module_groups'] = []
    assert 'Unclassified module' in analyze(root, policy)['errors'][0]


def test_cli_report_does_not_rewrite_baseline(project, capsys):
    root, policy, write = project
    write('empire.query')
    config = root / 'docs/architecture-contract.json'
    config.parent.mkdir()
    config.write_text(json.dumps(policy), 'utf-8')
    original = config.read_bytes()
    target = root / 'report.json'
    assert main(['report', '--root', str(root), '--output', str(target)]) == 0
    assert json.loads(target.read_text('utf-8'))['passed']
    assert config.read_bytes() == original
    assert 'PASS architecture' in capsys.readouterr().out


def test_current_project_has_reviewed_debt_without_new_dependencies():
    root = Path(__file__).resolve().parents[1]
    policy = json.loads((root / 'docs/architecture-contract.json').read_text('utf-8'))
    boundary = [d for d in policy['debt']
                if d['rule'] in {'reader_to_execution', 'misplaced_source_contract'}]
    assert policy['baseline']['collector_boundary_count'] == 16
    # Later migrations may retire reviewed exceptions; the historical count is
    # not a requirement to preserve those imports or to keep stale exemptions.
    assert len(boundary) <= 16
    assert sum(d['rule'] == 'reader_to_execution' for d in boundary) <= 6
    assert all(d['reason'] and d['names'] for d in policy['debt'])
    report = analyze(root, policy)
    assert report['passed'], report['errors'] + report['new_debt']
