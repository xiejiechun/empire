"""Moved features and package reexports must still invalidate source-bound review."""
from types import SimpleNamespace

import pytest

from scripts import documentation_contract as contract


def source(root, module, contents='', *, package=False):
    path = root / 'src' / module.replace('.', '/')
    path = path / '__init__.py' if package else path.with_suffix('.py')
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(contents, encoding='utf-8')
    return path


def test_feature_relative_imports_packages_and_reexports_are_all_bound_without_execution(tmp_path):
    marker = tmp_path / 'executed.txt'
    source(tmp_path, 'empire', package=True)
    source(tmp_path, 'empire.features', package=True)
    source(tmp_path, 'empire.features.news', 'from .query import Reader\n', package=True)
    source(tmp_path, 'empire.features.news.ui',
           'from . import Reader\nfrom . import source\nfrom ..shared import contract\n'
           'import empire.features.news.formatting as formatting\n'
           f'open({str(marker)!r}, "w").write("must never execute")\n')
    source(tmp_path, 'empire.features.news.query', 'from .contract import VALUE\nclass Reader: pass\n')
    source(tmp_path, 'empire.features.news.contract', 'VALUE = 1\n')
    source(tmp_path, 'empire.features.news.source', 'from . import query\n')
    source(tmp_path, 'empire.features.news.formatting')
    source(tmp_path, 'empire.features.shared', package=True)
    source(tmp_path, 'empire.features.shared.contract', 'VALUE = 2\n')
    source(tmp_path, 'empire.features.unrelated', 'raise RuntimeError("unreachable")\n')
    expected = {
        'src/empire/__init__.py', 'src/empire/features/__init__.py',
        'src/empire/features/news/__init__.py', 'src/empire/features/news/ui.py',
        'src/empire/features/news/query.py', 'src/empire/features/news/contract.py',
        'src/empire/features/news/source.py', 'src/empire/features/news/formatting.py',
        'src/empire/features/shared/__init__.py', 'src/empire/features/shared/contract.py',
    }
    first = contract.reachable_sources(tmp_path, ['empire.features.news.ui'])
    assert set(first) == expected and list(first) == sorted(expected)
    assert first == contract.reachable_sources(tmp_path, ['empire.features.news.ui'] * 3)
    assert not marker.exists()
    source(tmp_path, 'empire.features.news.contract', 'VALUE = 3\n')
    second = contract.reachable_sources(tmp_path, ['empire.features.news.ui'])
    assert {key for key in first if first[key] != second[key]} == {'src/empire/features/news/contract.py'}


def test_legacy_consumers_follow_shared_sources_and_feature_packages(tmp_path):
    source(tmp_path, 'empire.plugins.collectors.old',
           'from empire.sources import html\nfrom empire.features.news import Reader\n')
    source(tmp_path, 'empire.sources', 'from .html import Document\n', package=True)
    source(tmp_path, 'empire.sources.html', 'class Document: pass\n')
    source(tmp_path, 'empire.features.news', 'from .query import Reader\n', package=True)
    source(tmp_path, 'empire.features.news.query', 'class Reader: pass\n')
    bound = contract.reachable_sources(tmp_path, ['empire.plugins.collectors.old'])
    assert set(bound) == {
        'src/empire/plugins/collectors/old.py', 'src/empire/sources/__init__.py',
        'src/empire/sources/html.py', 'src/empire/features/news/__init__.py',
        'src/empire/features/news/query.py',
    }


def test_package_named_as_storage_file_resolves_relative_reexport(tmp_path):
    source(tmp_path, 'empire.features.news', 'from .contract import VALUE\n', package=True)
    source(tmp_path, 'empire.features.news.contract', 'VALUE = 1\n')
    assert contract.reachable_sources(tmp_path, ['empire.features.news.__init__']) == (
        contract.reachable_sources(tmp_path, ['empire.features.news']))


def test_namespace_packages_and_bom_source_do_not_hide_explicit_children(tmp_path):
    source(tmp_path, 'empire.features.news.ui', '\ufefffrom . import query\n')
    source(tmp_path, 'empire.features.news.query', 'VALUE = 1\n')
    assert set(contract.reachable_sources(tmp_path, ['empire.features.news.ui'])) == {
        'src/empire/features/news/ui.py', 'src/empire/features/news/query.py'}


@pytest.mark.parametrize('statement', ['from .....outside import value', 'from .... import value'])
def test_relative_import_cannot_escape_source_package(tmp_path, statement):
    source(tmp_path, 'empire.features.news.ui', statement)
    with pytest.raises(ValueError, match='escapes package'):
        contract.reachable_sources(tmp_path, ['empire.features.news.ui'])


def test_module_package_collision_cannot_silently_select_one_source(tmp_path):
    source(tmp_path, 'empire.features.news.ui')
    source(tmp_path, 'empire.features.news.ui', package=True)
    with pytest.raises(ValueError, match='Ambiguous'):
        contract.reachable_sources(tmp_path, ['empire.features.news.ui'])


def test_reexported_feature_change_requires_that_features_document_review(tmp_path, monkeypatch):
    source(tmp_path, 'empire.features.news', 'from .query import Reader\n', package=True)
    source(tmp_path, 'empire.features.news.query', 'class Reader: pass\n')
    coverage = {'pages': {'news': ['News']}, 'tasks': {}, 'storage': {'mysql': {}, 'redis': {}}}
    plugin = type('NewsPagePlugin', (), {'__module__': 'empire.features.news'})()
    article = SimpleNamespace(title='News', summary='', group='', body='Original instructions')
    manager = SimpleNamespace(entries={}, providers={})
    monkeypatch.setattr(contract, 'declarations', lambda root: (manager, {'news': plugin}, {}))
    monkeypatch.setattr(contract, 'read_articles', lambda path: [article])
    monkeypatch.setattr(contract, 'storage_snapshots', lambda *args: {})
    monkeypatch.setattr(contract, 'verify_coverage', lambda root: coverage)
    monkeypatch.setattr(contract, 'product_sources', lambda root: contract.reachable_sources(
        root, ['empire.features.news']))
    monkeypatch.setattr(contract, 'content_digest', lambda root, coverage: article.body)
    (tmp_path / 'docs').mkdir()
    contract.record_review(tmp_path, 'Initial fixture review')
    source(tmp_path, 'empire.features.news.query', 'class Reader:\n    changed_behavior = True\n')
    with pytest.raises(RuntimeError, match='page:news'):
        contract.record_review(tmp_path, 'Unrelated change', 'Global reason cannot hide this feature')
    article.body = 'Updated behavior instructions'
    contract.record_review(tmp_path, 'Reviewed changed query behavior')
    contract.verify_review(tmp_path)
