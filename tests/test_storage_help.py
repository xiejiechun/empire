import os
import re

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


def test_grouped_directory_and_ranked_offline_search():
    app = QApplication.instance() or QApplication([])
    page = StorageHelpPage(None)
    try:
        assert [page.index.topLevelItem(i).text(0) for i in range(page.index.topLevelItemCount())] == list(CATEGORIES)
        assert not page.index.topLevelItem(CATEGORIES.index('技术参考')).isExpanded()
        assert not page.index.topLevelItem(CATEGORIES.index('数据库参考')).isExpanded()
        data = page.index.topLevelItem(2)
        assert [data.child(i).text(0) for i in range(data.childCount())] == [
            "证券基础", "交易与行情", "公司事件", "财务报表", "行业与指数", "资讯", "财务数据", "股东数据", "公司行动"]
        page.search.setText("复权")
        assert page.index.topLevelItem(0).text(0) == "自算复权因子与行情"
        assert "全部分类" in page.scope.text()
        page.search.setText("baseline_revision")
        assert 'Redis collection-control' in page.items
        assert "baseline_revision" in page.browser.toPlainText()
        page.search.setText("不存在的参数XYZ")
        assert page.index.topLevelItemCount() == 0
        assert "没有匹配" in page.browser.toPlainText()
        assert page.chapters.count() == 0
        page.open_topic("开始使用")
        assert page.index.topLevelItemCount() == len(CATEGORIES)
    finally:
        page.deleteLater()
        app.processEvents()


def test_database_directory_and_direct_object_lookup():
    app = QApplication.instance() or QApplication([])
    page = StorageHelpPage(None)
    try:
        database = page.index.topLevelItem(CATEGORIES.index('数据库参考'))
        groups = {database.child(i).text(0): database.child(i) for i in range(database.childCount())}
        assert set(groups) == {'总览', 'MySQL', 'Redis'}
        assert groups['MySQL'].childCount() == 55
        assert groups['Redis'].childCount() == 18
        page.search.setText('MySQL suspension_source_date')
        assert page.index.topLevelItem(0).text(0) == 'MySQL suspension_source_date'
        assert 'source_date' in page.browser.toPlainText()
        page.open_topic('Redis fingerprint-expiry')
        assert '数据库参考 / Redis' in page.location.text()
        assert '<namespace>:archive:fingerprints:v1:<dataset>:<source>:expiry' in page.browser.toPlainText()
        assert 'ZSET' in page.browser.toPlainText()
    finally:
        page.deleteLater()
        app.processEvents()


def test_all_articles_render_and_literal_storage_placeholders_survive():
    app = QApplication.instance() or QApplication([])
    page = StorageHelpPage(None)
    try:
        page.open_topic("股票表字段（stock）")
        visible = page.browser.toPlainText()
        assert "<namespace>:stocks:committed:<source>" in visible
        assert "DATETIME(6)" in visible
        for article in articles():
            page.open_topic(article.title)
            assert article.title in page.browser.toPlainText()
            assert page.summary.text() == article.summary
            assert page.chapters.count() > 1
            expected = re.findall(r"\]\((help:[^)]*)\)", article.body)
            from PySide6.QtCore import QUrl
            actual = set()
            block = page.browser.document().begin()
            while block.isValid():
                fragments = block.begin()
                while not fragments.atEnd():
                    fragment = fragments.fragment()
                    if fragment.isValid() and fragment.charFormat().isAnchor():
                        actual.add(QUrl(fragment.charFormat().anchorHref()).toString())
                    fragments += 1
                block = block.next()
            for target in expected:
                assert QUrl(target).toString() in actual, (article.title, target)
            assert '](help:' not in page.browser.toPlainText(), article.title
    finally:
        page.deleteLater()
        app.processEvents()


def test_related_links_history_and_reading_positions_survive_recreation():
    from PySide6.QtCore import QUrl

    app = QApplication.instance() or QApplication([])
    page = StorageHelpPage(None)
    page.resize(800, 580)
    page.show()
    try:
        page.open_topic("采集出口与频控")
        page.chapters.setCurrentIndex(3)
        assert page.browser.textCursor().position() == page.chapters.itemData(3)
        app.processEvents()
        position = page.browser.verticalScrollBar().value()
        assert position > 0
        page.open_link(QUrl("help:增发"))
        assert page.current_topic == "增发"
        assert "公司事件" in page.location.text()
        page.move_history(-1)
        assert page.current_topic == "采集出口与频控"
        assert page.browser.verticalScrollBar().value() == position
        page.move_history(1)
        assert page.current_topic == "增发"
        state = page.save_ui_state()
        recreated = StorageHelpPage(None)
        recreated.resize(800, 580)
        recreated.show()
        recreated.restore_ui_state(state)
        assert recreated.current_topic == "增发"
        recreated.move_history(-1)
        assert recreated.current_topic == "采集出口与频控"
        assert recreated.positions["采集出口与频控"] == position
        recreated.deleteLater()
        page.open_link(QUrl('help:MySQL%20stock_listing'))
        assert page.current_topic == 'MySQL stock_listing'
        assert 'listing_date' in page.browser.toPlainText()
    finally:
        page.deleteLater()
        app.processEvents()
