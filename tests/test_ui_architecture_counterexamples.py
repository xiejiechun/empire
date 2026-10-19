"""Moving a UI module or changing import syntax cannot evade UI boundaries."""
import pytest

from scripts.ui_architecture_contract import check_ui_architecture


@pytest.fixture
def ui_project(tmp_path):
    policy = dict(schema=1, owners={
        'desktop': {'kind': 'platform'}, 'ui_components': {'kind': 'platform'},
        'application': {'kind': 'platform'}, 'news': {'kind': 'business'},
    }, module_groups=[], feature_layouts=[], debt=[])

    def write(module, contents='', *, role='ui', owner='news', package=False):
        path = tmp_path / 'src' / module.replace('.', '/')
        path = path / '__init__.py' if package else path.with_suffix('.py')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(contents, encoding='utf-8')
        policy['module_groups'].append(dict(modules=[module], role=role, owner=owner, reason='Fixture'))
        return path
    return tmp_path, policy, write


@pytest.mark.parametrize('module', ['empire.plugins.ui.news', 'empire.features.news.ui',
                                  'empire.features.news.presentation.detail'])
def test_role_classified_ui_move_cannot_evade_350_line_limit(ui_project, module):
    root, policy, write = ui_project
    write(module, '# physical line\n' * 351)
    assert any('350' in error for error in check_ui_architecture(root, policy))


def test_feature_layout_role_is_used_without_filename_special_cases(ui_project):
    root, policy, write = ui_project
    write('empire.features.news.presentation.detail', '# line\n' * 351)
    policy['module_groups'].clear()
    policy['feature_layouts'] = [dict(prefix='empire.features.news', owner='news',
        reason='Reviewed feature layout', roles={'presentation': 'ui'})]
    assert any('350' in error for error in check_ui_architecture(root, policy))


@pytest.mark.parametrize('statement', [
    'from empire.features.news.ui import Page',
    'import empire.features.news.ui as news',
    'from ..features.news.ui import Page',
    'from ..features.news import ui',
])
def test_shell_cannot_import_moved_page_using_alternative_syntax(ui_project, statement):
    root, policy, write = ui_project
    write('empire.features.news.ui', 'class Page: pass\n')
    write('empire.desktop.window', statement, role='kernel', owner='desktop')
    assert any('desktop shell' in error for error in check_ui_architecture(root, policy))


@pytest.mark.parametrize('statement', [
    'from .collection import CollectionPage',
    'import empire.plugins.ui.collection as collection',
    'from empire.plugins.ui import collection',
])
def test_existing_collection_page_boundary_handles_relative_and_module_imports(ui_project, statement):
    root, policy, write = ui_project
    write('empire.plugins.ui.collection', 'class CollectionPage: pass\n')
    write('empire.plugins.ui.news', statement)
    assert any('collection page' in error for error in check_ui_architecture(root, policy))


def test_shared_controls_cannot_depend_on_feature_business_page(ui_project):
    root, policy, write = ui_project
    write('empire.features.news.ui', 'class Page: pass\n')
    write('empire.components.cards', 'from ..features.news.ui import Page\n',
          role='shared_ui', owner='ui_components')
    assert any('shared UI' in error for error in check_ui_architecture(root, policy))


def test_public_symbol_does_not_allow_shared_ui_to_import_business(ui_project):
    root, policy, write = ui_project
    write('empire.plugins.ui.preview_cards', 'class CardReader: pass\nprivate=1\n')
    policy['module_groups'][-1]['public_symbols'] = ['CardReader']
    caller = write('empire.components.cards',
                   'from empire.plugins.ui.preview_cards import CardReader\n',
                   role='shared_ui', owner='ui_components')
    assert any('shared UI' in error for error in check_ui_architecture(root, policy))
    caller.write_text('import empire.plugins.ui.preview_cards as cards\n', encoding='utf-8')
    assert any('shared UI' in error for error in check_ui_architecture(root, policy))


@pytest.mark.parametrize('statement', ['from .queries import QueryScope',
                                      'import empire.plugins.ui.queries as queries'])
def test_common_retains_its_existing_no_plugin_import_rule(ui_project, statement):
    root, policy, write = ui_project
    write('empire.plugins.ui.queries', 'class QueryScope: pass\n', role='shared_ui', owner='ui_components')
    write('empire.plugins.ui.common', statement, role='shared_ui', owner='ui_components')
    assert any('common controls' in error for error in check_ui_architecture(root, policy))


@pytest.mark.parametrize('statement,allowed', [
    ('from empire.features.data_browser.catalog import DataCatalogPage', True),
    ('from empire.features.data_browser.catalog import hidden', False),
    ('import empire.features.data_browser.catalog as catalog', False),
    ('from . import catalog', False),
])
def test_catalog_public_symbol_exception_is_exact(ui_project, statement, allowed):
    root, policy, write = ui_project
    write('empire.features.data_browser.catalog', 'class DataCatalogPage: pass\nhidden=1\n')
    write('empire.plugins.ui.news', statement)
    errors = check_ui_architecture(root, policy)
    assert bool(errors) is not allowed


def test_unclassified_moved_module_fails_instead_of_silently_skipping(ui_project):
    root, policy, write = ui_project
    write('empire.features.news.unregistered', '# line\n' * 351)
    policy['module_groups'].clear()
    assert any('Unclassified module' in error for error in check_ui_architecture(root, policy))


def test_static_scan_does_not_execute_pages_and_preserves_legacy_task_rule(ui_project, tmp_path):
    root, policy, write = ui_project
    marker = tmp_path / 'executed.txt'
    write('empire.features.news.ui.tasks', f'open({str(marker)!r}, "w").write("executed")\n'
          'VALUE="sina-news"\n')
    assert any('hard-code' in error for error in check_ui_architecture(root, policy))
    assert not marker.exists()
