import os
from concurrent.futures import Future
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from empire.plugins.ui.news import NewsPage  # noqa: E402


class Runtime:
    def __init__(self):
        self.requests = []

    def invoke(self, *args):
        result = Future()
        self.requests.append((args, result))
        return result


def result(title="测试新闻", ident=1):
    return {"total": 1, "offset": 0, "limit": 50, "rows": [{"news_id": ident, "title": title,
        "content": "正文含 <b>纯文本</b>", "published_at": "2026-09-23T00:00:00",
        "source_updated_at": "2026-09-23T00:01:00", "is_important": True,
        "tags": [{"id": "9", "name": "焦点"}], "url": "https://finance.sina.com.cn/7x24/"}]}


def test_news_page_discards_stale_results_and_keeps_plain_content():
    app = QApplication.instance() or QApplication([])
    runtime = Runtime()
    shell = SimpleNamespace(runtime=runtime, cfg={}, shutting_down=False, navigate=lambda route: None)
    page = NewsPage(shell)
    page.timer.stop()
    page.show()
    try:
        page.tick()
        first = runtime.requests[-1][1]
        page.search.setText("黄金")
        page.search_changed()
        first.set_result(result("旧查询"))
        page.tick()
        assert page.total == 0
        assert runtime.requests[-1][0] == ("news.query", "list_news", "黄金", 0, 50, False)
        runtime.requests[-1][1].set_result(result("黄金新闻"))
        page.tick()
        assert page.total == 1
        assert page.table.item(0, 1).text() == "黄金新闻"
        assert "08:00" in page.detail.toPlainText()
        assert "<b>纯文本</b>" in page.detail.toPlainText()
        page.copy_content()
        assert QApplication.clipboard().text() == "正文含 <b>纯文本</b>"
        page.important.setChecked(True)
        assert runtime.requests[-1][0][-1] is True
        pending = len(runtime.requests)
        shell.shutting_down = True
        page.reload()
        page.tick()
        assert len(runtime.requests) == pending
        assert not page.timer.isActive()
    finally:
        page.close()
        page.deleteLater()
        app.processEvents()
