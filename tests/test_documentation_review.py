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
                 "Empire.spec", "docs/documentation-coverage.json"):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / name, target)
    target = tmp_path / "docs/documentation-coverage.json"
    coverage = json.loads(target.read_text(encoding="utf-8"))
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
