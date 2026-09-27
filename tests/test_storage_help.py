import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.core.config import project_root  # noqa: E402
from empire.plugins.ui.help import CATEGORIES, StorageHelpPage, articles, topics  # noqa: E402


def test_reference_covers_all_current_schema_columns_and_example_settings():
    documentation = "\n".join(topics().values())
    schema = (project_root() / "sql/schema.sql").read_text(encoding="utf-8")
    for table, body in re.findall(r"CREATE TABLE IF NOT EXISTS (\w+) \((.*?)\) ENGINE", schema, re.S):
        assert table in documentation
        for column in re.findall(r"^    ([a-z][a-z_]+)\s", body, re.M):
            assert column in documentation, (table, column)
    example = (project_root() / "config/app.example.toml").read_text(encoding="utf-8")
    for key in re.findall(r"^(\w+)\s*=", example, re.M):
        assert key in documentation, key
    assert "每个采集项目独立保留最近 100 条" in documentation
    assert "不写入 MySQL" in documentation
    assert "每个项目最近 300 条" in documentation
    assert "64 KiB" in documentation
    assert "先修复并验证" in documentation
    assert "原始内容的 SHA-256" in documentation
    assert "stock_universe_member" not in documentation
    assert "ingest_event" not in documentation


def test_help_is_offline_searchable_and_has_empty_search_feedback():
    app = QApplication.instance() or QApplication([])
    page = StorageHelpPage(None)
    try:
        assert page.index.count() == 3
        page.search.setText("baseline_revision")
        assert page.index.count() == 1
        assert "baseline_revision" in page.browser.toPlainText()
        page.search.setText("插件内核")
        assert page.index.count() == 1
        assert page.index.item(0).text() == "系统架构"
        architecture = page.browser.toPlainText()
        assert "Redis 待归档消息与断点" in architecture
        assert "MySQL 业务表" in architecture
        assert "Qt 主线程" in architecture
        page.search.setText("不存在的参数XYZ")
        assert page.index.count() == 0
        assert "没有匹配" in page.browser.toPlainText()
        page.search.clear()
        assert page.index.count() == 3
        assert Path(__import__("empire.plugins.ui.help", fromlist=["__file__"]).__file__).with_name("storage_reference.md").exists()
    finally:
        page.deleteLater()
        app.processEvents()



def test_document_categories_and_stock_reference_rendering():
    app = QApplication.instance() or QApplication([])
    page = StorageHelpPage(None)
    try:
        assert len({a.title for a in articles()}) == len(articles())
        assert tuple(page.tabs.tabText(i) for i in range(page.tabs.count())) == CATEGORIES
        assert page.index.item(0).text() == "开始使用"
        page.tabs.setCurrentIndex(1)
        assert [page.index.item(i).text() for i in range(page.index.count())] == [
            "股票列表", "财经快讯", "交易日历"]
        page.search.setText("stock")
        assert "全部分类" in page.scope.text()
        page.show_topic("股票表字段（stock）")
        visible = page.browser.toPlainText()
        assert "<namespace>:stocks:committed:<source>" in visible
        assert "不是 SQL 提交时刻，也不是最近一次成功核验时间" in visible
        assert "09:10" in visible and "09:00" in visible
        assert "DATETIME(6)" in visible
        assert "数据的新鲜度" not in visible
        page.tabs.setCurrentIndex(2)
        assert not page.search.text()
        assert page.current_topic == "股票表字段（stock）"
        assert "系统架构" in [page.index.item(i).text() for i in range(page.index.count())]
        for article in articles():
            page.show_topic(article.title)
            assert article.title in page.browser.toPlainText()
    finally:
        page.deleteLater()
        app.processEvents()
