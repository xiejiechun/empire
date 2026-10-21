"""Selection is conservative; registration is never promoted to execution evidence."""
import json

import pytest

from scripts.change_impact import local_path, report


@pytest.fixture
def project(tmp_path):
    policy = dict(schema=1, owners={'news': {'kind': 'business'}, 'holders': {'kind': 'business'},
                                  'application': {'kind': 'platform'}}, module_groups=[])
    assembly = dict(schema=1, bindings=dict(plugins={}, tests={}), semantic=dict(preparation={}))

    def write(path, text='', *, owner='news', role='query'):
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding='utf-8')
        if path.startswith('src/') and path.endswith('.py'):
            module = path[4:-3].replace('/', '.').removesuffix('.__init__')
            if not any(module in group['modules'] for group in policy['module_groups']):
                policy['module_groups'].append(dict(modules=[module], owner=owner, role=role,
                                                  reason='Explicit test ownership'))
        return target

    write('src/empire/news/query.py', 'VALUE = 1')
    write('src/empire/holders/query.py', 'VALUE = 2', owner='holders')
    write('tests/test_news.py', 'from empire.news.query import VALUE\ndef test_news(): assert VALUE == 1')
    write('tests/test_holders.py', 'from empire.holders.query import VALUE\ndef test_holders(): assert VALUE == 2')
    return tmp_path, policy, assembly, write


def select(project, *paths, **kwargs):
    root, policy, assembly, _ = project
    return report(root, paths, policy, assembly, **kwargs)


def test_business_change_selects_its_regression_without_claiming_execution(project):
    value = select(project, 'src/empire/news/query.py')
    assert value['mode'] == 'selected'
    assert value['selected_tests'] == ['tests/test_news.py']
    assert value['affected_businesses'] == ['news']
    assert value['execution_evidence'][0]['status'] == 'not_verified'
    assert value['live_validation']['status'] == 'not_assessed'
    assert value['verification_status'] == 'not_complete'
    assert value['official_release'] == 'full_gate_required'


def test_cross_business_consumer_expands_owner_and_reverse_tests(project):
    _, _, _, write = project
    write('src/empire/holders/query.py', 'from empire.news.query import VALUE', owner='holders')
    value = select(project, 'src/empire/news/query.py')
    assert value['affected_businesses'] == ['holders', 'news']
    assert value['selected_tests'] == ['tests/test_holders.py', 'tests/test_news.py']


def test_complete_business_expansion_reaches_fixed_point_and_adds_consumers_registration(project):
    _, _, assembly, write = project
    write('src/empire/news/source.py', 'VALUE = 3', role='parser')
    write('src/empire/holders/query.py', 'from empire.news.source import VALUE', owner='holders')
    write('src/empire/holders/other.py', 'VALUE = 4', owner='holders')
    write('tests/test_holder_other.py', 'from empire.holders.other import VALUE')
    write('tests/test_holder_registered.py', 'from empire.news.query import VALUE')
    assembly['bindings']['plugins']['data.holders'] = {'module': 'empire.holders.query'}
    assembly['bindings']['tests']['data.holders:holders'] = {
        'archive_tests': ['tests/test_holder_registered.py']}
    assembly['semantic']['preparation']['data.holders:holders'] = {
        'requirement': 'holders', 'project_id': 'ths-holders'}
    value = select(project, 'src/empire/news/query.py')
    assert value['mode'] == 'selected'
    assert value['affected_businesses'] == ['holders', 'news']
    assert 'tests/test_holder_other.py' in value['selected_tests']
    assert value['contributions'][0]['project'] == 'ths-holders'


def test_same_owner_ui_includes_common_lifecycle_guards(project):
    _, _, _, write = project
    write('src/empire/news/ui.py', 'from empire.news.query import VALUE', role='ui')
    for name in ('ui_architecture', 'desktop_runtime', 'desktop_interaction'):
        write(f'tests/test_{name}.py', 'def test_contract(): pass')
    value = select(project, 'src/empire/news/ui.py')
    assert value['mode'] == 'selected'
    assert set(value['selected_tests']) == {'tests/test_news.py', 'tests/test_ui_architecture.py',
                                          'tests/test_desktop_runtime.py', 'tests/test_desktop_interaction.py'}


@pytest.mark.parametrize('role', ['contract', 'api', 'composition', 'dataset_registry'])
def test_public_contract_and_composition_force_full(project, role):
    _, _, _, write = project
    write('src/empire/news/public.py', 'VALUE = 1', role=role)
    value = select(project, 'src/empire/news/public.py')
    assert value['mode'] == 'full'
    assert value['selected_tests'] == ['tests/test_holders.py', 'tests/test_news.py']


@pytest.mark.parametrize('path', ['src/empire/news/deleted.py', 'docs/changed.md', 'unknown.bin'])
def test_deleted_missing_and_unclassified_inputs_force_full(project, path):
    assert select(project, path)['mode'] == 'full'


def test_source_unknown_dynamic_dependency_forces_full(project):
    _, _, _, write = project
    write('src/empire/news/worker.py', 'import importlib\nimportlib.import_module(name)')
    value = select(project, 'src/empire/news/query.py')
    assert value['mode'] == 'full' and value['errors']


def test_unknown_dynamic_test_helper_selects_its_consumers(project):
    _, _, _, write = project
    write('tests/loader.py', 'from importlib import import_module as load\nvalue = load(name)')
    write('tests/test_late.py', 'from .loader import value')
    value = select(project, 'src/empire/news/query.py')
    assert value['mode'] == 'selected'
    assert 'tests/test_late.py' in value['selected_tests']


@pytest.mark.parametrize('dynamic', [
    "import importlib\nload = importlib.import_module\nload(module_name)",
    "import importlib.util\nspec = importlib.util.spec_from_file_location('x', path)\n"
    "spec.loader.exec_module(module)",
    "import importlib as loader\ngetattr(loader, method)(module_name)",
    "import runpy\nrunpy.run_path(path)",
    "getattr(__builtins__, method)(text)",
])
def test_dynamic_loader_with_unrelated_repository_import_is_still_selected(project, dynamic):
    _, _, _, write = project
    write('tests/loader.py', 'from empire.holders.query import VALUE\n' + dynamic)
    write('tests/test_late.py', 'from .loader import VALUE')
    value = select(project, 'src/empire/news/query.py')
    assert 'tests/test_late.py' in value['selected_tests']


def test_parent_initialization_and_fixture_modules_are_dependencies(project):
    _, _, _, write = project
    write('src/empire/news/__init__.py', 'from .query import VALUE', role='package')
    write('tests/helpers.py', 'from empire.news.query import VALUE')
    write('tests/test_helper.py', 'from .helpers import VALUE')
    value = select(project, 'src/empire/news/__init__.py')
    assert set(value['selected_tests']) == {'tests/test_news.py', 'tests/test_helper.py'}


def test_conftest_change_selects_its_subtree(project):
    _, _, _, write = project
    write('tests/integration/conftest.py')
    write('tests/integration/test_a.py', 'from empire.holders.query import VALUE')
    value = select(project, 'tests/integration/conftest.py')
    assert value['mode'] == 'selected'
    assert value['selected_tests'] == ['tests/integration/test_a.py']


def test_real_contribution_adds_registered_source_and_archive_cases(project):
    _, _, assembly, write = project
    assembly['bindings']['plugins']['data.news'] = {'module': 'empire.news.query'}
    assembly['bindings']['tests']['data.news:news'] = {
        'source_tests': ['tests/test_registered.py'], 'archive_tests': ['tests/integration/test_archive.py']}
    assembly['semantic']['preparation']['data.news:news'] = {'requirement': 'news', 'project_id': 'sina-news'}
    write('tests/test_registered.py', 'from empire.holders.query import VALUE')
    write('tests/integration/test_archive.py', 'from empire.holders.query import VALUE')
    value = select(project, 'src/empire/news/query.py')
    assert value['mode'] == 'selected'
    assert value['contributions'][0]['project'] == 'sina-news'
    assert 'tests/test_registered.py' in value['selected_tests']
    assert 'tests/integration/test_archive.py' in value['selected_tests']


def test_missing_registered_file_cannot_be_omitted_or_pass(project):
    _, _, assembly, _ = project
    assembly['bindings']['plugins']['data.news'] = {'module': 'empire.news.query'}
    assembly['bindings']['tests']['data.news:news'] = {'source_tests': ['tests/test_missing.py']}
    assembly['semantic']['preparation']['data.news:news'] = {'requirement': 'news', 'project_id': 'sina-news'}
    value = select(project, 'src/empire/news/query.py')
    assert value['mode'] == 'full' and value['errors']
    assert 'tests/test_missing.py' in value['selected_tests']
    assert value['selection_status'] == 'review_required'


@pytest.mark.parametrize('status,expected', [('passed', 'passed'), ('failure', 'not_passed'),
                                           ('skipped', 'not_passed'), ('error', 'not_passed')])
def test_execution_evidence_requires_every_case_passing(project, status, expected):
    evidence = dict(checked_at='2026-10-19T00:00:00+00:00', cases=[
        dict(module='tests.test_news', name='test_normal', status='passed'),
        dict(module='tests.test_news', name='test_replay', status=status)])
    value = select(project, 'src/empire/news/query.py', evidence=evidence, evidence_error='')
    assert value['execution_evidence'][0]['status'] == expected
    assert value['verification_status'] == 'not_complete'


def test_stale_evidence_never_counts_as_pass(project):
    evidence = dict(checked_at='old', cases=[dict(module='tests.test_news', name='test_x', status='passed')])
    value = select(project, 'src/empire/news/query.py', evidence=evidence, evidence_error='source changed')
    assert value['execution_evidence'][0]['status'] == 'not_verified'


def test_static_read_does_not_execute_application_or_test_code(project):
    root, _, _, write = project
    marker = root / 'unsafe.txt'
    text = f"open({str(marker)!r}, 'w').write('ran')\nraise RuntimeError('imported')"
    write('src/empire/news/query.py', text)
    write('tests/test_news.py', 'from empire.news.query import VALUE\n' + text)
    select(project, 'src/empire/news/query.py')
    assert not marker.exists()


@pytest.mark.parametrize('value', ['../secret', '/outside', 'C:/config.toml', 'config.toml',
                                   'config/local.toml', 'src\\escape.py', './tests/test_a.py'])
def test_paths_are_canonical_bounded_and_never_private(project, value):
    with pytest.raises(ValueError):
        local_path(project[0], value)


def test_report_is_deterministic_for_repeated_and_reordered_inputs(project):
    first = select(project, 'src/empire/news/query.py', 'tests/test_news.py')
    second = select(project, 'tests/test_news.py', 'src/empire/news/query.py', 'tests/test_news.py')
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


@pytest.mark.parametrize('damage', ['kind', 'plugins', 'tests', 'semantics', 'schema'])
def test_malformed_metadata_requires_all_tests_without_attesting_execution(project, damage):
    _, policy, assembly, _ = project
    if damage == 'kind':
        policy['owners']['news'] = None
    elif damage == 'schema':
        assembly['schema'] = 99
    elif damage == 'semantics':
        assembly['semantic'] = None
        assembly['bindings']['tests']['data.news:news'] = {'source_tests': ['tests/test_news.py']}
        assembly['bindings']['plugins']['data.news'] = {'module': 'empire.news.query'}
    else:
        assembly['bindings'][damage] = None
    value = select(project, 'src/empire/news/query.py')
    assert value['mode'] == 'full' and value['errors']
    assert value['selected_tests'] == ['tests/test_holders.py', 'tests/test_news.py']
    assert all(item['status'] == 'not_verified' for item in value['execution_evidence'])


@pytest.mark.parametrize('code', [
    'import importlib\nload = importlib.import_module\nload(name)',
    'import runpy\nrunpy.run_path(path)',
    'import importlib as loader\ngetattr(loader, method)(name)',
])
def test_indirect_product_loaders_cannot_narrow_regression(project, code):
    _, _, _, write = project
    write('src/empire/news/dynamic.py', code)
    value = select(project, 'src/empire/news/query.py')
    assert value['mode'] == 'full' and value['errors']


def test_qt_exec_and_redis_eval_methods_are_not_python_dynamic_loaders(project):
    _, _, _, write = project
    write('src/empire/news/query.py', 'app.exec()\nredis.eval(script, 1, key)')
    assert select(project, 'src/empire/news/query.py')['mode'] == 'selected'
