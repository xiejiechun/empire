"""Counterexamples for authoritative fragments and the checked reader artifact."""
import json
import shutil
from pathlib import Path

import pytest

from empire.plugins.ui import help_content
from scripts.documentation_build import (
    REFERENCE,
    SOURCE_INDEX,
    check_generated,
    compile_help,
    generate,
)
from scripts.release_identity import assert_inputs, input_inventory


def fragment(title, link=''):
    return (f'<!-- topic:技术参考|{title} -->\n<!-- summary:这是可独立阅读的完整说明摘要。 -->\n'
            f'# {title}\n\n## 使用与边界\n\n{link or "本段只用于离线文档生成测试。"}\n')


def write(root, name, contents):
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(contents, encoding='utf-8', newline='\n')
    return target


@pytest.fixture
def help_project(tmp_path):
    # Creation order differs from the explicitly declared reader order.
    write(tmp_path, 'src/empire/features/news/docs/help/second.md', fragment('第二主题'))
    write(tmp_path, 'src/empire/documentation/topics/first.md', fragment('第一主题', '[第二](help:第二主题)'))
    index = {'schema': 1, 'sources': [
        {'owner': 'shared', 'path': 'src/empire/documentation/topics/first.md'},
        {'owner': 'news', 'path': 'src/empire/features/news/docs/help/second.md'},
    ]}
    write(tmp_path, SOURCE_INDEX, json.dumps(index))
    (tmp_path / REFERENCE).parent.mkdir(parents=True)
    return tmp_path


def test_generation_is_ordered_deterministic_and_cwd_independent(help_project, tmp_path, monkeypatch):
    root = help_project
    first = generate(root)
    target = root / REFERENCE
    timestamp = target.stat().st_mtime_ns
    elsewhere = tmp_path / 'unrelated working directory'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert generate(root).content == first.content == target.read_bytes()
    assert target.stat().st_mtime_ns == timestamp  # Repeated generation does not rewrite.
    assert [value.title for value in first.articles] == ['第一主题', '第二主题']
    assert check_generated(root).evidence() == first.evidence()
    assert first.origins['第二主题']['owner'] == 'news'
    assert '\r' not in first.content.decode('utf-8')


@pytest.mark.parametrize('changed', ['source', 'aggregate', 'index-order'])
def test_stale_aggregate_is_rejected_without_modifying_any_input(help_project, changed):
    root = help_project
    generate(root)
    if changed == 'source':
        write(root, 'src/empire/features/news/docs/help/second.md', fragment('第二主题') + '\n新增限制。\n')
    elif changed == 'aggregate':
        with (root / REFERENCE).open('ab') as target:
            target.write(b'edited by hand\n')
    else:
        index = json.loads((root / SOURCE_INDEX).read_text())
        index['sources'].reverse()
        write(root, SOURCE_INDEX, json.dumps(index))
    before = input_inventory(root)
    with pytest.raises(RuntimeError, match='aggregate is stale'):
        check_generated(root)
    assert_inputs(root, before)


@pytest.mark.parametrize('damage', ['missing', 'orphan', 'duplicate-path', 'duplicate-topic',
                                   'path-traversal', 'owner', 'bad-summary', 'broken-link',
                                   'relative-link', 'multiple-topics', 'case-collision'])
def test_invalid_fragment_sets_fail_closed(help_project, damage):
    root = help_project
    index = json.loads((root / SOURCE_INDEX).read_text())
    second = index['sources'][1]['path']
    if damage == 'missing':
        (root / second).unlink()
    elif damage == 'orphan':
        write(root, 'src/empire/features/news/docs/help/orphan.md', fragment('未登记'))
    elif damage == 'duplicate-path':
        index['sources'].append(index['sources'][1])
    elif damage == 'duplicate-topic':
        write(root, second, fragment('第一主题'))
    elif damage == 'path-traversal':
        index['sources'][1]['path'] = 'src/empire/features/news/docs/help/../../../../outside.md'
    elif damage == 'owner':
        index['sources'][1]['owner'] = 'holders'
    elif damage == 'bad-summary':
        write(root, second, fragment('第二主题').replace('这是可独立阅读的完整说明摘要。', '短'))
    elif damage == 'broken-link':
        write(root, second, fragment('第二主题', '[失效](help:不存在)'))
    elif damage == 'relative-link':
        write(root, second, fragment('第二主题', '[仅在源码目录存在](README.md)'))
    elif damage == 'multiple-topics':
        write(root, second, fragment('第二主题') + fragment('第三主题'))
    else:
        index['sources'].append({'owner': 'news', 'path': second.replace('second', 'SECOND')})
    write(root, SOURCE_INDEX, json.dumps(index))
    before = input_inventory(root)
    with pytest.raises((ValueError, RuntimeError, OSError)):
        compile_help(root)
    assert_inputs(root, before)
    assert not (root / REFERENCE).exists()


@pytest.mark.parametrize('name', [
    'src/empire/features/news/docs/help/nested/orphan.md',
    'src/empire/documentation/topics/nested/orphan.md',
    'src/empire/features/news/docs/help/ORPHAN.md',
    'src/empire/documentation/topics/orphan.MD',
])
def test_undeclared_nested_or_noncanonical_fragment_paths_cannot_be_hidden(help_project, name):
    generate(help_project)
    write(help_project, name, fragment('未登记文章'))
    before = input_inventory(help_project)
    with pytest.raises(ValueError, match='Invalid help source path'):
        check_generated(help_project)
    assert_inputs(help_project, before)


def test_reader_has_one_identical_resource_path_in_source_and_packaged_layout(help_project, monkeypatch):
    expected = generate(help_project)
    source_module = help_project / REFERENCE.replace('storage_reference.md', 'help_content.py')
    monkeypatch.setattr(help_content, '__file__', str(source_module))
    source = help_content.articles()
    bundled = help_project / 'portable/_internal/empire/plugins/ui'
    bundled.mkdir(parents=True)
    shutil.copyfile(help_project / REFERENCE, bundled / 'storage_reference.md')
    monkeypatch.setattr(help_content, '__file__', str(bundled / 'help_content.py'))
    assert help_content.articles() == source == list(expected.articles)
    (bundled / 'storage_reference.md').unlink()
    with pytest.raises(FileNotFoundError):
        help_content.articles()  # No fallback to developer fragments or an older resource.


def test_formal_aggregate_has_exactly_the_authoritative_article_sequence():
    root = Path(__file__).resolve().parents[1]
    bundle = check_generated(root)
    assert list(bundle.articles) == help_content.articles()
    assert len(bundle.origins) == len(bundle.articles)
    assert all(origin['path'] in bundle.inputs for origin in bundle.origins.values())


def test_linked_fragment_is_rejected_without_following_or_rewriting_it(help_project):
    root = help_project
    path = root / 'src/empire/features/news/docs/help/second.md'
    outside = root / 'outside.md'
    outside.write_bytes(path.read_bytes())
    path.unlink()
    path.symlink_to(outside)
    original = outside.read_bytes()
    with pytest.raises((ValueError, RuntimeError), match='link|Link|symlink|Symbolic'):
        compile_help(root)
    assert outside.read_bytes() == original
    assert not (root / REFERENCE).exists()


def test_cli_relative_report_belongs_to_build_independent_of_cwd(help_project, tmp_path, monkeypatch):
    from scripts import documentation_build as compiler
    generate(help_project)
    monkeypatch.setattr(compiler, '__file__', str(help_project / 'scripts/documentation_build.py'))
    elsewhere = tmp_path / 'different-cwd'
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr('sys.argv', ['documentation_build.py', 'check', '--report', 'current/help.json'])
    compiler.main()
    report = help_project / 'build/current/help.json'
    assert json.loads(report.read_text('utf8')) == check_generated(help_project).evidence()
    assert not (elsewhere / 'current').exists()
    monkeypatch.setattr('sys.argv', ['documentation_build.py', 'check', '--report', '../outside.json'])
    with pytest.raises(RuntimeError, match='escaped'):
        compiler.main()
