import json
import shutil
from pathlib import Path

import pytest

from empire.plugins.ui.help_content import read_articles
from scripts.documentation_contract import record_review, verify_coverage, verify_review


@pytest.fixture
def documented_project(tmp_path):
    root = Path(__file__).resolve().parents[1]
    for name in ("src/empire/plugins/ui/storage_reference.md", "config/app.example.toml",
                 "src/empire/plugins/collection/rules.json",
                 "Empire.spec", "docs/documentation-coverage.json",
                 "src/empire/features/stocks/ui.py"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    target = tmp_path / "docs/documentation-coverage.json"
    coverage = json.loads(target.read_text(encoding="utf-8"))
    names = {'sql/schema.sql', 'sql/business-schema.json', *coverage['storage']['redis_constructors']}
    for kind in ('mysql', 'redis'):
        names.update(p for entry in coverage['storage'][kind].values() for p in entry['sources'])
    for name in names:
        destination = tmp_path / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, destination)
    coverage["guides"] = []
    target.write_text(json.dumps(coverage), encoding="utf-8")
    return tmp_path


def test_source_change_cannot_reuse_review_without_document_update(documented_project):
    root = documented_project
    record_review(root, "核对首次说明")
    verify_review(root)
    new_source = root / "src/empire/new_feature.py"
    new_source.write_text("FEATURE = True\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="文档审阅已过期"):
        verify_review(root)
    with pytest.raises(RuntimeError, match="说明未更新"):
        record_review(root, "只刷新摘要")
    record_review(root, "核对内部重构", "新增内部常量未改变入口、默认值、数据或恢复规则")
    verify_review(root)
    new_source.unlink()
    with pytest.raises(RuntimeError, match="文档审阅已过期"):
        verify_review(root)


def test_missing_or_changed_rule_invalidates_contract(documented_project):
    target = documented_project / 'src/empire/plugins/collection/rules.json'
    original = target.read_text(encoding='utf-8')
    record_review(documented_project, '逐任务核实规则')
    value = json.loads(original)
    value['tasks']['sina-news']['end'] = '修改后的来源窗口'
    target.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(RuntimeError, match='审阅已过期'):
        verify_review(documented_project)
    del value['tasks']['sina-news']
    target.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    with pytest.raises(ValueError, match='覆盖'):
        verify_coverage(documented_project)


def test_page_without_usage_article_or_retired_topic_fails(documented_project):
    target = documented_project / "docs/documentation-coverage.json"
    value = json.loads(target.read_text(encoding="utf-8"))
    del value["pages"]["income"]
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="页面登记不一致"):
        verify_coverage(documented_project)
    value["pages"]["income"] = ["已删除的文章"]
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="缺少有效说明"):
        verify_coverage(documented_project)
    value["pages"]["income"] = ["财报存储与断点"]
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="只有技术参考"):
        verify_coverage(documented_project)


def test_content_change_and_broken_offline_links_fail(documented_project):
    root = documented_project
    record_review(root, "核对说明")
    target = root / "src/empire/plugins/ui/storage_reference.md"
    contents = target.read_text(encoding="utf-8")
    target.write_text(contents + "\n补充限制。\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="文档审阅已过期"):
        verify_review(root)
    target.write_text(contents + "\n[不存在](help:已删除主题)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="链接目标不存在"):
        read_articles(target)


def test_unrelated_article_update_cannot_hide_changed_feature(documented_project):
    root = documented_project
    record_review(root, "核对当前功能")
    code = root / "src/empire/features/stocks/ui.py"
    code.write_text(code.read_text(encoding="utf-8") + "\n# revised stock behavior\n", encoding="utf-8")
    article = root / "src/empire/plugins/ui/storage_reference.md"
    article.write_text(article.read_text(encoding="utf-8") + "\n无关技术参考的补充。\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="page:stocks"):
        record_review(root, "修改了其他文章", "全局原因不能代替逐功能核对")
    record_review(root, "核对股票内部注释", exceptions={"page:stocks": "只改内部注释，市场筛选、查询和复制行为均未改变"})
    verify_review(root)


def test_offline_links_require_encoded_spaces(documented_project):
    target = documented_project / 'src/empire/plugins/ui/storage_reference.md'
    contents = target.read_text(encoding='utf-8')
    target.write_text(contents.replace('help:MySQL%20stock', 'help:MySQL stock', 1), encoding='utf-8')
    with pytest.raises(ValueError, match='空格须编码'):
        read_articles(target)


def test_collector_without_data_page_still_requires_coverage(documented_project):
    target = documented_project / "docs/documentation-coverage.json"
    value = json.loads(target.read_text(encoding="utf-8"))
    del value["tasks"]["sina-stocks"]
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="采集任务登记不一致"):
        verify_coverage(documented_project)


def test_data_articles_require_structured_user_sections(documented_project):
    target = documented_project / "src/empire/plugins/ui/storage_reference.md"
    contents = target.read_text(encoding="utf-8").replace("## 字段与日期", "## 只有技术字段", 1)
    target.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match="缺少章节 字段与日期"):
        read_articles(target)


def test_data_page_cannot_be_documented_only_by_homepage(documented_project):
    target = documented_project / "docs/documentation-coverage.json"
    value = json.loads(target.read_text(encoding="utf-8"))
    value["pages"]["stocks"] = ["开始使用"]
    target.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RuntimeError, match="数据页面缺少数据范围说明"):
        verify_coverage(documented_project)


def test_every_table_requires_its_own_dictionary(documented_project):
    target = documented_project / 'docs/documentation-coverage.json'
    value = json.loads(target.read_text(encoding='utf-8'))
    value['storage']['mysql'].pop('suspension_source_date')
    target.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(RuntimeError, match='逐表说明登记不一致'):
        verify_coverage(documented_project)


@pytest.mark.parametrize('change', ['column', 'type', 'index'])
def test_dictionary_is_checked_locally_against_ddl(documented_project, change):
    target = documented_project / 'src/empire/plugins/ui/storage_reference.md'
    content = target.read_text(encoding='utf-8')
    start = content.index('<!-- topic:数据库参考|MySQL stock_listing -->')
    end = content.index('<!-- topic:', start + 5)
    article = content[start:end]
    if change == 'column':
        # Still present in source-specific technical prose: global word matching would pass.
        article = '\n'.join(line for line in article.splitlines() if not line.startswith('| `history` |')) + '\n'
    elif change == 'type':
        article = article.replace('DATE NOT NULL', 'DATE NULL', 1)
    else:
        article = article.replace('KEY ix_listing_date (listing_date, unified_code)',
                                  'KEY ix_listing_date (unified_code, listing_date)')
    target.write_text(content[:start] + article + content[end:], encoding='utf-8')
    with pytest.raises(RuntimeError, match='字典与 DDL 不一致|索引或约束说明未同步'):
        verify_coverage(documented_project)


@pytest.mark.parametrize('expression', [
    "f'{store.prefix}:new_feature:{ident}'", "key + ':new-index'",
])
def test_new_redis_constructor_requires_registration(documented_project, expression):
    target = documented_project / 'src/empire/plugins/new_feature.py'
    target.write_text('def key(store, ident):\n    return ' + expression + '\n', encoding='utf-8')
    with pytest.raises(RuntimeError, match='Redis 键构造发生变化'):
        verify_coverage(documented_project)


def test_redis_constructor_requires_the_actual_object_owner(documented_project):
    target = documented_project / 'docs/documentation-coverage.json'
    value = json.loads(target.read_text(encoding='utf-8'))
    entries = value['storage']['redis_constructors']['src/empire/plugins/infra/redis_store.py']
    entries[next(iter(entries))] = ['errors']
    target.write_text(json.dumps(value), encoding='utf-8')
    with pytest.raises(RuntimeError, match='Redis 键构造缺少逐项归属'):
        verify_coverage(documented_project)


def test_unrelated_article_cannot_cover_storage_source_changes(documented_project):
    root = documented_project
    record_review(root, '核对每张表与每类键')
    code = root / 'src/empire/plugins/pipeline/fingerprints.py'
    code.write_text(code.read_text(encoding='utf-8') + '\n# Changed cache lifetime contract\n', encoding='utf-8')
    article = root / 'src/empire/plugins/ui/storage_reference.md'
    article.write_text(article.read_text(encoding='utf-8') + '\n仅修改无关文章。\n', encoding='utf-8')
    with pytest.raises(RuntimeError, match='redis:fingerprints'):
        record_review(root, '更新了其他对象的正文')
